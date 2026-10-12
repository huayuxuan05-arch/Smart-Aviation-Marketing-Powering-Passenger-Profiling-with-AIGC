"""发布包校验、冲突保护、路径安全及断点下载测试，全部写入D盘项目临时目录。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib,io,json,unittest,zipfile
import distribution_io as dist

class DistributionTests(unittest.TestCase):
 def setUp(self):
  root=Path(__file__).resolve().parent/'runtime/tmp';root.mkdir(parents=True,exist_ok=True)
  self.temp=TemporaryDirectory(dir=root);self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def spec(self,raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 def bundle(self,entries):
  path=self.root/'bundle.zip'
  with zipfile.ZipFile(path,'w') as archive:
   for name,raw in entries:archive.writestr(name,raw)
  return path,{'bundle':self.spec(path.read_bytes()),'files':[{'path':name,**self.spec(raw)} for name,raw in entries]}
 def test_join_checks_each_part_and_final_model(self):
  parts=[]
  for i,raw in enumerate([b'original',b'-bytes']):
   path=self.root/f'part-{i}';path.write_bytes(raw);parts.append((path,self.spec(raw)))
  target=dist.join_parts(parts,self.root/'full.gguf',self.spec(b'original-bytes'))
  self.assertEqual(target.read_bytes(),b'original-bytes')
  parts[0][0].write_bytes(b'corrupt!')
  with self.assertRaises(ValueError):dist.join_parts(parts,self.root/'bad.gguf',self.spec(b'original-bytes'))
  self.assertFalse((self.root/'bad.gguf').exists())
 def test_restore_exact_original_workbooks_and_models(self):
  entries=[('数据集/01_航班信息.xlsx',b'original workbook'),('航旅智策应用/runtime/models/marketing_models.joblib',b'trained weights')]
  package,manifest=self.bundle(entries);target=self.root/'fresh-machine'
  dist.restore_bundle(package,target,manifest)
  for name,raw in entries:self.assertEqual((target/name).read_bytes(),raw)
  dist.restore_bundle(package,target,manifest)
 def test_restore_refuses_to_overwrite_existing_different_data(self):
  package,manifest=self.bundle([('数据集/01_航班信息.xlsx',b'expected')]);target=self.root/'existing-machine'
  existing=target/'数据集/01_航班信息.xlsx';existing.parent.mkdir(parents=True);existing.write_bytes(b'user data')
  with self.assertRaises(ValueError):dist.restore_bundle(package,target,manifest)
  self.assertEqual(existing.read_bytes(),b'user data')
 def test_restore_rejects_path_escape_and_unknown_files(self):
  package,manifest=self.bundle([('../escape.txt',b'bad')])
  with self.assertRaises(ValueError):dist.restore_bundle(package,self.root/'target',manifest)
  self.assertFalse((self.root/'escape.txt').exists())
  package,manifest=self.bundle([('数据集/01_航班信息.xlsx',b'expected')]);manifest['files']=[]
  with self.assertRaises(ValueError):dist.restore_bundle(package,self.root/'target',manifest)
 def test_bundle_hash_must_match_before_restore(self):
  package,manifest=self.bundle([('数据集/01_航班信息.xlsx',b'expected')]);package.write_bytes(package.read_bytes()+b'corrupt')
  with self.assertRaises(ValueError):dist.restore_bundle(package,self.root/'target',manifest)
 def test_resume_uses_matching_byte_range_and_verified_bytes(self):
  path=self.root/'download.bin';path.with_suffix('.bin.downloading').write_bytes(b'first-')
  class Response(io.BytesIO):
   status=206
   headers={'Content-Range':'bytes 6-11/12'}
  with patch.object(dist.urllib.request,'urlopen',return_value=Response(b'second')) as request:
   dist.download('https://example.invalid/asset',path,self.spec(b'first-second'))
  self.assertEqual(request.call_args.args[0].get_header('Range'),'bytes=6-')
  self.assertEqual(path.read_bytes(),b'first-second')
 def test_bad_resume_range_cannot_append_to_original_partial_file(self):
  path=self.root/'download.bin';partial=path.with_suffix('.bin.downloading');partial.write_bytes(b'first-')
  class Response(io.BytesIO):
   status=206
   headers={'Content-Range':'bytes 0-5/12'}
  with patch.object(dist.urllib.request,'urlopen',side_effect=lambda *a,**k:Response(b'second')),patch.object(dist.time,'sleep'):
   with self.assertRaises(ValueError):dist.download('https://example.invalid/asset',path,self.spec(b'first-second'))
  self.assertEqual(partial.read_bytes(),b'first-');self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
