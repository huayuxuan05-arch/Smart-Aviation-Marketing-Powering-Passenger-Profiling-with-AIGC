"""模型服务异常不得保存为有效创意；不启动推理或访问网络。"""
import json,os,unittest
from unittest.mock import patch
import local_generation as gen
from aigc_config import ALIAS,MODEL_NAME,ROOT,MODEL_FILE

class GenerationTests(unittest.TestCase):
 def setUp(self):
  self.mode=patch.dict(os.environ,{'AEROLENS_GENERATION_MODE':'local-model'});self.mode.start();self.addCleanup(self.mode.stop)
 def response(self,**changes):
  result={'model':ALIAS,'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'title':'给假期留一段从容时光','text':'按自己的节奏安排旅程，先了解航线参考，再决定出发的方向。','palette':'teal','art':'coast'})}}],'usage':{'completion_tokens':75}}
  result.update(changes);return result

 def run_generation(self,response):
  with patch.object(gen,'ensure'),patch.object(gen,'rpc',return_value=response) as request:
   return gen.generate('三亚','国庆','景区探索'),request

 def test_real_model_provenance_and_native_template_request(self):
  result,request=self.run_generation(self.response())
  self.assertIn(MODEL_NAME,result['engine']);self.assertEqual(result['model_alias'],ALIAS)
  body=request.call_args.args[1];self.assertFalse(body['chat_template_kwargs']['enable_thinking'])
  self.assertEqual(body['messages'][1]['role'],'user');self.assertNotIn('prompt',body)
  self.assertEqual(result['usage']['completion_tokens'],75)

 def test_other_model_response_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'其他模型'):self.run_generation(self.response(model='old-1.5b'))

 def test_truncated_json_is_rejected(self):
  response=self.response();response['choices'][0]['finish_reason']='length'
  with self.assertRaisesRegex(ValueError,'完整'):self.run_generation(response)
  response=self.response();response['choices'][0]['message']['content']='{"title":'
  with self.assertRaisesRegex(ValueError,'JSON'):self.run_generation(response)

 def test_missing_or_unexpected_fields_are_rejected(self):
  for value in [{'title':'缺少字段'},{'title':'正常标题','text':'正常文案','palette':'unsupported','art':'city'}]:
   response=self.response();response['choices'][0]['message']['content']=json.dumps(value)
   with self.assertRaises(ValueError):self.run_generation(response)

 def test_unsafe_copy_is_flagged_for_review(self):
  response=self.response();value=json.loads(response['choices'][0]['message']['content']);value['text']='保证最低价格100元';response['choices'][0]['message']['content']=json.dumps(value)
  result,_=self.run_generation(response)
  self.assertIn('保证',result['risk_flags']);self.assertIn('未提供的数值声明',result['risk_flags'])

 def test_health_does_not_reuse_a_different_model_on_same_port(self):
  with patch.object(gen,'rpc',side_effect=[{'status':'ok'},{'model_path':str(ROOT/'old-model.gguf')}]):self.assertFalse(gen.health())
  with patch.object(gen,'rpc',side_effect=[{'status':'ok'},{'model_path':str(ROOT/MODEL_FILE)},{'data':[{'id':'wrong-alias'}]}]):self.assertFalse(gen.health())
  with patch.object(gen,'rpc',side_effect=[{'status':'ok'},{'model_path':str(ROOT/MODEL_FILE)},{'data':[{'id':ALIAS}]}]):self.assertTrue(gen.health())

 def extraction(self,text,items):
  response={'model':gen.ALIAS,'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'items':items},ensure_ascii=False)}}]}
  with patch.object(gen,'ensure'),patch.object(gen,'rpc',return_value=response):
   return gen.extract_preferences(text,['上海'],['成都'],{'pace':['轻松','充实'],'lodging_priority':['安静休息']})

 def test_reworded_evidence_does_not_abort_other_model_findings(self):
  result=self.extraction('从上海去成都，酒店别太吵，想轻松一点',[
   {'field':'origin','value':'上海','evidence':'从上海'},
   {'field':'lodging_priority','value':'安静休息','evidence':'酒店要安静'},
   {'field':'pace','value':'轻松','evidence':'想轻松一点'}])
  self.assertEqual([i['field'] for i in result['items']],['origin','pace'])
  self.assertEqual(result['unverified_fields'],['lodging_priority'])

 def test_typography_is_reanchored_to_original_text_without_changing_negation(self):
  text='预算４０００元，\n想 轻松一点，不要春秋航空'
  self.assertEqual(gen.original_evidence(text,'预算4000元'),'预算４０００元')
  self.assertEqual(gen.original_evidence(text,'“想轻松一点”'),'想 轻松一点')
  self.assertIsNone(gen.original_evidence(text,'我要春秋航空'))
  self.assertIsNone(gen.original_evidence(text,''))
  self.assertIsNone(gen.original_evidence(text,None))

 def test_conflicting_or_missing_evidence_is_isolated_per_field(self):
  result=self.extraction('想轻松一点但也想充实，从上海去成都',[
   {'field':'pace','value':'轻松','evidence':'轻松一点'},
   {'field':'pace','value':'充实','evidence':'想充实'},
   {'field':'origin','value':'上海','evidence':'从上海'},
   {'field':'lodging_priority','value':'安静休息'},
   {'field':'unsupported','value':'anything','evidence':'上海'}])
  self.assertEqual(result['items'],[{'field':'origin','value':'上海','evidence':'从上海'}])
  self.assertEqual(set(result['unverified_fields']),{'pace','lodging_priority'})

if __name__=='__main__':unittest.main()
