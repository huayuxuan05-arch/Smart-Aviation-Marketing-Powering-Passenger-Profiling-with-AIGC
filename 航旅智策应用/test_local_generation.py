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

if __name__=='__main__':unittest.main()
