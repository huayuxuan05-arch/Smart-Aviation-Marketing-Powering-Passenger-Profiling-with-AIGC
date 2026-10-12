"""仅从已观察行为训练；全量10000用户、完整时间隔离、无隐藏偏好标签。"""
import os
os.environ.setdefault('OMP_NUM_THREADS','8')
os.environ.setdefault('OPENBLAS_NUM_THREADS','8')
from pathlib import Path
from datetime import datetime,timedelta
import json,time,hashlib,threading
import numpy as np
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import average_precision_score,precision_recall_fscore_support,roc_auc_score,brier_score_loss,accuracy_score
from data_layer import RUNTIME,connect,SOURCE_HASHES,VERSION
from algorithm_layer import HOLIDAYS

ROOT=RUNTIME/'models'; ROOT.mkdir(exist_ok=True)
BASE_DATE=datetime(2023,12,1)
SEED=20261012
TYPES=['destination','scenic','hotel','airfare','guide']
CHANNELS=['百度','携程','同程','小红书','B站','飞猪']
FEATURES=['近7天关注占比','近30天关注占比','近60天关注占比','14天衰减关注占比','最近关注距今天数','重复访问占比','收藏对象数','目的地信息占比','景区内容占比','酒店内容占比','机票查询占比','攻略内容占比','目的地停留强度','近期关注变化','明确假期计划占比','明确出行计划占比','近期预算均值','预算证据数','全局机票查询占比','全局攻略访问占比','全局重复访问占比','当前假期临近度','用户内容停留强度']
CLUSTER_FEATURES=['目的地信息','景区关注','酒店关注','机票查询','攻略准备','重复关注','收藏动作','有明确日期','有预算证据','平均停留','近7天机票关注','近7天攻略关注']
_CACHE=None
_LOCK=threading.Lock()

def day_index(value):return (datetime.fromisoformat(str(value)[:10])-BASE_DATE).days

def load_data():
 global _CACHE
 if _CACHE is not None:return _CACHE
 cache=ROOT/'behavior_arrays.npz'
 with connect() as c:
  users=[dict(r) for r in c.execute('SELECT * FROM users ORDER BY user_id')]
  objects=[dict(r) for r in c.execute('SELECT * FROM objects ORDER BY object_id')]
 destinations=sorted({o['destination'] for o in objects})
 if cache.exists():
  a=dict(np.load(cache,allow_pickle=False));_CACHE=(a,users,objects,destinations);return _CACHE
 uidx={u['user_id']:i for i,u in enumerate(users)};didx={d:i for i,d in enumerate(destinations)};oidx={o['object_id']:i for i,o in enumerate(objects)}
 shape=(397,len(users))
 a={name:np.zeros(shape,dtype=dtype) for name,dtype in [('dest','int16'),('type','uint8'),('channel','uint8'),('hour','uint8'),('dwell','float32'),('repeat','uint8'),('action','int8'),('obj','int16'),('budget','float32'),('travel','int16'),('favtime','int32'),('visit','int32')]}
 a['travel'].fill(-1);a['budget'].fill(np.nan);a['favtime'].fill(-1)
 def seconds(s):return int((datetime.fromisoformat(s)-BASE_DATE).total_seconds())
 with connect() as c:
  cur=c.execute('SELECT user_id,behavior_date,destination,object_type,channel,search_at_cst,dwell_seconds,is_repeat_visit,favorite_action,object_id,price_limit_cny,travel_date,favorite_at_cst,visit_at_cst FROM behaviors ORDER BY rowid')
  for n,r in enumerate(cur,1):
   j=uidx[r[0]];i=day_index(r[1]);a['dest'][i,j]=didx[r[2]];a['type'][i,j]=TYPES.index(r[3]);a['channel'][i,j]=CHANNELS.index(r[4]);a['hour'][i,j]=int(r[5][11:13]);a['dwell'][i,j]=r[6];a['repeat'][i,j]=r[7];a['action'][i,j]=1 if r[8] in ('add','favorite','collect') else -1 if r[8] in ('remove','unfavorite','cancel') else 0;a['obj'][i,j]=oidx[r[9]]
   if r[10] is not None:a['budget'][i,j]=r[10]
   if r[11]:a['travel'][i,j]=day_index(r[11])
   if r[12]:a['favtime'][i,j]=seconds(r[12])
   a['visit'][i,j]=seconds(r[13])
   if n%500000==0:print('ARRAY_READ',n,flush=True)
 np.savez_compressed(cache,**a)
 _CACHE=(a,users,objects,destinations)
 return _CACHE

def snapshot(asof):
 """截至北京时间当天末尾；对尚未完成的访问/收藏按子事件截断。"""
 a,users,objects,dests=load_data();t=day_index(asof);n=len(users);k=len(dests);ids=np.arange(n);end=(t+1)*86400-1
 if not 30<=t<397:raise ValueError('营销画像截点须位于2023-12-31至2024-12-31')
 count={w:np.zeros((n,k),np.float32) for w in [7,30,60]};decay=np.zeros((n,k),np.float32);recency=np.full((n,k),61,np.float32);typ=np.zeros((n,k,5),np.float32);dwell=np.zeros((n,k),np.float32);repeat=np.zeros((n,k),np.float32);explicit=np.zeros((n,k),np.float32);holiday=np.zeros((n,k),np.float32)
 budget_sum=np.zeros(n,np.float32);budget_n=np.zeros(n,np.float32);ctypes=np.zeros((n,5),np.float32);channels=np.zeros((n,6),np.float32);hours=np.zeros((n,24),np.float32)
 for age in range(min(60,t+1)):
  z=t-age;d=a['dest'][z]
  for w in count:
   if age<w:count[w][ids,d]+=1
  decay[ids,d]+=2**(-age/14);recency[ids,d]=np.minimum(recency[ids,d],age)
  if age<30:
   visited=a['visit'][z]<=end;complete=np.maximum(0,np.minimum(a['dwell'][z],end-a['visit'][z]))
   typ[ids,d,a['type'][z]]+=1;ctypes[ids,a['type'][z]]+=1;dwell[ids,d]+=complete/300;repeat[ids,d]+=a['repeat'][z]*visited
   plans=a['travel'][z]>t;explicit[ids,d]+=plans
   for h in HOLIDAYS:
    valid=plans&(a['travel'][z]>=day_index(h['start']))&(a['travel'][z]<=day_index(h['end']))
    holiday[ids,d]+=valid
   good=~np.isnan(a['budget'][z]);budget_sum+=np.nan_to_num(a['budget'][z]);budget_n+=good
   channels[ids,a['channel'][z]]+=1;hours[ids,a['hour'][z]]+=1
 fav=np.zeros((n,len(objects)),bool)
 for z in range(t+1):
  active=(a['action'][z]!=0)&(a['favtime'][z]<=end)&(a['favtime'][z]>=0)
  ii=ids[active];fav[ii,a['obj'][z,active]]=a['action'][z,active]>0
 favdest=np.zeros((n,k),np.float32);didx={d:i for i,d in enumerate(dests)}
 for oidx,o in enumerate(objects):favdest[:,didx[o['destination']]]+=fav[:,oidx]
 def tile(v):return np.broadcast_to(v[:,None],(n,k))
 meanbudget=np.divide(budget_sum,budget_n,out=np.zeros(n,np.float32),where=budget_n>0)
 proximity=min((max(0,(datetime.fromisoformat(h['start'])-datetime.fromisoformat(asof[:10])).days) for h in HOLIDAYS if h['end']>=asof[:10]),default=90)
 values=[count[7]/7,count[30]/30,count[60]/min(60,t+1),decay/max(1,sum(2**(-i/14) for i in range(min(60,t+1)))),recency/61,repeat/30,np.log1p(favdest),*[typ[:,:,i]/30 for i in range(5)],dwell/30,count[7]/7-count[30]/30,holiday/30,explicit/30,tile(meanbudget/5000),tile(budget_n/30),tile(ctypes[:,3]/30),tile(ctypes[:,4]/30),tile(np.sum(repeat,axis=1)/30),np.full((n,k),max(0,1-proximity/30),np.float32),tile(np.sum(dwell,axis=1)/30)]
 X=np.stack(values,axis=-1).astype(np.float32)
 cluster=np.column_stack([ctypes/30,np.sum(repeat,axis=1)/30,np.sum((a['action'][max(0,t-29):t+1]>0)&(a['favtime'][max(0,t-29):t+1]<=end),axis=0)/30,np.sum(explicit,axis=1)/30,budget_n/30,np.sum(dwell,axis=1)/30,np.mean(a['type'][t-6:t+1]==3,axis=0),np.mean(a['type'][t-6:t+1]==4,axis=0)]).astype(np.float32)
 return {'X':X,'count':count,'cluster':cluster,'channels':channels,'hours':hours,'budget':meanbudget,'budget_n':budget_n,'favdest':favdest,'asof':asof,'day':t}

def targets(t,horizon=7):
 a,users,objects,dests=load_data();n=len(users);k=len(dests);counts=np.zeros((n,k),np.int8);fare=np.zeros((n,k),np.int8);fav=np.zeros((n,k),np.int8);ids=np.arange(n)
 if t+horizon>=397:raise ValueError('标签窗口不完整')
 for z in range(t+1,t+horizon+1):
  d=a['dest'][z];counts[ids,d]+=1;fare[ids,d]+=a['type'][z]==3;fav[ids,d]+=(a['action'][z]>0)&(a['favtime'][z]<=(t+horizon+1)*86400-1)
 return {'continue':(counts>=2).astype(np.uint8),'fare':(fare>0).astype(np.uint8),'favorite':(fav>0).astype(np.uint8),'attention':(counts>0).astype(np.uint8)}

def ranking_metrics(y,scores,k=3):
 order=np.argsort(-scores,axis=1,kind='stable')[:,:k];rel=np.take_along_axis(y,order,axis=1);num=y.sum(axis=1);valid=num>0;discount=1/np.log2(np.arange(2,k+2));dcg=(rel*discount).sum(axis=1);ideal=np.array([sum(discount[:min(int(v),k)]) for v in num]);return {'recall_at_3':float(np.mean(rel.sum(axis=1)[valid]/num[valid])),'ndcg_at_3':float(np.mean(dcg[valid]/ideal[valid])),'eligible_snapshots':int(valid.sum()),'no_relevant_snapshots':int((~valid).sum())}

def train():
 started=time.time();a,users,objects,dests=load_data();train_dates=[f'2024-{m:02}-15' for m in range(1,7)];val_dates=[f'2024-{m:02}-15' for m in range(7,10)];test_dates=[f'2024-{m:02}-15' for m in range(10,13)]
 def dataset(dates):
  xs=[];ys=[];snap=[]
  for date in dates:
   print('FEATURES',date,flush=True);s=snapshot(date);y=targets(s['day']);xs.append(s['X'].reshape(-1,len(FEATURES)));ys.append(y);snap.append(s['cluster'])
  return np.concatenate(xs),{key:np.concatenate([y[key].reshape(-1) for y in ys]) for key in ys[0]},np.concatenate(snap)
 X,y,C=dataset(train_dates);V,v,VC=dataset(val_dates);T,z,TC=dataset(test_dates)
 report={'version':'holiday-ml-v1','source_version':VERSION,'source_sha256':SOURCE_HASHES,'users':len(users),'behavior_rows':3970000,'protocol':{'warmup':'2023-12','train_dates':train_dates,'validation_dates':val_dates,'test_dates':test_dates,'horizon':7,'feature_days':[7,30,60],'candidate_destinations':dests,'train_pair_rows':len(X),'validation_pair_rows':len(V),'test_pair_rows':len(T),'label_definitions':{'continue':'截点后7天同目的地至少2次搜索过程','fare':'截点后7天同目的地至少1次机票价格查询','favorite':'截点后7天同目的地至少1次已发生收藏动作'},'split':'按时间阶段划分；所有10000用户参与各阶段；不是新用户泛化实验','feature_cutoff':'仅截点当天末尾及之前；访问时长和收藏按事件时间遮蔽','frozen_test':True},'features':FEATURES,'models':{},'ranking':{},'warnings':['全部用户行为与营销反馈为模拟；预测是未来关注代理，不是购票概率','同一用户跨阶段出现；仅评价既有用户的后续需求','评估截点固定为每月15日；元旦仅可做冷启动演示，早于训练完成的节日使用历史基线','没有真实座位、库存、费用与满意度标签；不报告真实客座率、增量转化或ROI']}
 models={};scaler=StandardScaler().fit(X);Xs=scaler.transform(X)
 for label in ['continue','fare','favorite']:
  print('TRAIN_LOGISTIC',label,len(X),flush=True)
  model=SGDClassifier(loss='log_loss',alpha=.0001,max_iter=16,tol=.0001,random_state=SEED,early_stopping=False).fit(Xs,y[label]);models[label]=model
  if model.n_iter_>=model.max_iter:report['warnings'].append(label+'辅助逻辑回归达到固定16轮迭代上限，可能尚未收敛；保留实际结果，不据此宣称最优')
 print('TRAIN_HIST_BOOST',flush=True)
 boost=HistGradientBoostingClassifier(max_iter=65,max_leaf_nodes=15,max_bins=64,learning_rate=.12,l2_regularization=3,early_stopping=False,random_state=SEED).fit(X,y['continue']);models['boost']=boost
 pred={key:mod.predict_proba(V if key=='boost' else scaler.transform(V))[:,1] for key,mod in models.items()}
 selection={key:average_precision_score(v['continue'],pred[key]) for key in ['continue','boost']};selected=max(selection,key=selection.get)
 for key,mod in models.items():
  label='continue' if key=='boost' else key;vp=pred[key];thresholds=np.linspace(.03,.8,50);f1s=[precision_recall_fscore_support(v[label],vp>=th,average='binary',zero_division=0)[2] for th in thresholds];th=float(thresholds[int(np.argmax(f1s))]);tp=mod.predict_proba(T if key=='boost' else scaler.transform(T))[:,1];precision,recall,f1,_=precision_recall_fscore_support(z[label],tp>=th,average='binary',zero_division=0)
  report['models'][key]={'algorithm':'HistGradientBoostingClassifier' if key=='boost' else 'SGD logistic regression','target':label,'selected':key==selected,'threshold':th,'validation_pr_auc':float(average_precision_score(v[label],vp)),'test_pr_auc':float(average_precision_score(z[label],tp)),'test_roc_auc':float(roc_auc_score(z[label],tp)),'test_brier':float(brier_score_loss(z[label],tp)),'test_precision':float(precision),'test_recall':float(recall),'test_f1':float(f1),'test_positive_rate':float(np.mean(z[label]))}
  if label=='continue':report['ranking'][key]=ranking_metrics(z['continue'].reshape(-1,len(dests)),tp.reshape(-1,len(dests)))
 # Same candidates, same users, same dates, no future information for all baselines.
 baseline={name:[] for name in ['近30天频次','时间衰减规则','最近一次关注','固定画像','训练集热门']};fixed=snapshot('2024-06-30')['X'][:,:,1];pop=X[:,1].reshape(-1,len(dests)).mean(axis=0)
 for date in test_dates:
  s=snapshot(date);baseline['近30天频次'].append(s['X'][:,:,1]);baseline['时间衰减规则'].append(s['X'][:,:,3]);baseline['最近一次关注'].append(-s['X'][:,:,4]);baseline['固定画像'].append(fixed);baseline['训练集热门'].append(np.broadcast_to(pop,(len(users),len(dests))))
 for name,parts in baseline.items():report['ranking'][name]=ranking_metrics(z['continue'].reshape(-1,len(dests)),np.concatenate(parts))
 print('TRAIN_KMEANS',flush=True)
 cluster_scaler=StandardScaler().fit(C);km=MiniBatchKMeans(n_clusters=5,batch_size=2048,n_init=5,random_state=SEED).fit(cluster_scaler.transform(C));centers=cluster_scaler.inverse_transform(km.cluster_centers_);report['segments']=[{'id':i,'center':dict(zip(CLUSTER_FEATURES,map(float,row)))} for i,row in enumerate(centers)]
 # Channel and time preferences learned only from pre-cutoff behavior, predicts future access (not conversion).
 chx=[];chy=[];hty=[]
 for date in train_dates+val_dates+test_dates:
  s=snapshot(date);t=s['day'];cx=np.column_stack([s['channels']/30,s['hours']/30,s['cluster']]);chx.append(cx)
  future=a['channel'][t+1:t+8];hour=a['hour'][t+1:t+8]//4
  chy.append(np.array([np.bincount(future[:,i],minlength=6).argmax() for i in range(len(users))]));hty.append(np.array([np.bincount(hour[:,i],minlength=6).argmax() for i in range(len(users))]))
 chx=np.concatenate(chx);chy=np.concatenate(chy);hty=np.concatenate(hty);cs=StandardScaler().fit(chx[:60000]);cm=SGDClassifier(loss='log_loss',alpha=.001,max_iter=100,random_state=SEED).fit(cs.transform(chx[:60000]),chy[:60000]);hm=SGDClassifier(loss='log_loss',alpha=.001,max_iter=100,random_state=SEED).fit(cs.transform(chx[:60000]),hty[:60000])
 report['channel_model']={'task':'预测未来7天最常访问渠道（并列按固定渠道序；不代表最优转化渠道）','test_accuracy':float(accuracy_score(chy[90000:],cm.predict(cs.transform(chx[90000:])))),'majority_baseline':float(np.mean(chy[90000:]==np.bincount(chy[:60000]).argmax())),'channels':CHANNELS}
 report['time_model']={'task':'预测未来7天最常访问的4小时时段（并列按时段序；实际推送遵守安静时段）','test_accuracy':float(accuracy_score(hty[90000:],hm.predict(cs.transform(chx[90000:])))),'majority_baseline':float(np.mean(hty[90000:]==np.bincount(hty[:60000]).argmax()))}
 report['selected']=selected;report['training_seconds']=round(time.time()-started,2);report['trained_at']=datetime.now().isoformat(timespec='seconds')
 pack={'models':models,'scaler':scaler,'selected':selected,'cluster':km,'cluster_scaler':cluster_scaler,'channel':cm,'time':hm,'channel_scaler':cs,'report':report}
 joblib.dump(pack,ROOT/'marketing_models.joblib',compress=3);(ROOT/'training_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');write_manifest();print('COMPLETE',report['training_seconds'],selected,json.dumps(report['ranking'],ensure_ascii=False),flush=True)
 return report

_PACK=None

def write_manifest():
 import sklearn
 artifacts={}
 for name in ['behavior_arrays.npz','marketing_models.joblib','training_report.json']:
  path=ROOT/name
  with path.open('rb') as stream:artifacts[name]={'sha256':hashlib.file_digest(stream,'sha256').hexdigest(),'bytes':path.stat().st_size}
 (ROOT/'artifact_manifest.json').write_text(json.dumps({'source_sha256':SOURCE_HASHES,'numpy':np.__version__,'scikit_learn':sklearn.__version__,'seed':SEED,'artifacts':artifacts},ensure_ascii=False,indent=2),encoding='utf-8')

def model_pack():
 global _PACK
 if _PACK is None:
  if not (ROOT/'marketing_models.joblib').exists():raise ValueError('模型尚未训练完成，请稍后重试')
  _PACK=joblib.load(ROOT/'marketing_models.joblib')
 return _PACK

if __name__=='__main__':train()
