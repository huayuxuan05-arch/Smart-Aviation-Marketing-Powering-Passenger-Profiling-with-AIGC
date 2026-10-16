"""Portable install and model switching; tiny explicit fixture assets only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib,json,unittest,zipfile
import portable_models as models
import distribution_io

class PortableModelTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).parent/'runtime/tmp';base.mkdir(parents=True,exist_ok=True)
        self.tmp=TemporaryDirectory(dir=base);self.root=Path(self.tmp.name)
        raw=b'QA weights';self.model={'name':'Qwen3-4B-Q4_K_M.gguf','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'revision':'QA fixture'}
        self.part=self.root/'Qwen3-4B-Q4_K_M.gguf.part-001';self.part.write_bytes(raw)
        self.archive=self.root/'runtime.zip'
        with zipfile.ZipFile(self.archive,'w') as z:z.writestr('llama-server.exe',b'QA executable fixture - never executed')
        spec={'name':'runtime.zip','bytes':self.archive.stat().st_size,'sha256':distribution_io.sha256(self.archive)}
        self.manifest={'repository':'QA/fixture','release_tag':'QA-fixture','model':self.model,'model_parts':[{'name':self.part.name,'bytes':len(raw),'sha256':self.model['sha256']}],'runtimes':{'CPU':spec,'Vulkan':spec}}
    def tearDown(self):self.tmp.cleanup()
    def download(self,url,target,spec):return self.archive if spec['name']=='runtime.zip' else self.part

    def test_fresh_cpu_install_uses_own_paths_and_matching_weights(self):
        root=self.root/'fresh-model'
        with patch.object(models,'download',side_effect=self.download):profile=models.prepare_4b(self.manifest,'CPU',root)
        self.assertEqual(profile['device'],'none');self.assertEqual(profile['backend'],'CPU')
        self.assertTrue(Path(profile['model_file']).is_relative_to(root));self.assertTrue(Path(profile['executable']).is_relative_to(root))
        self.assertTrue(distribution_io.valid(Path(profile['model_file']),self.model))
        self.assertEqual(json.loads((root/'active_model.json').read_text(encoding='utf-8')),profile)

    def test_auto_reuses_verified_existing_model_without_downloading(self):
        root=self.root/'model'
        with patch.object(models,'download',side_effect=self.download):first=models.prepare_4b(self.manifest,'Vulkan',root)
        with patch.object(models,'download') as download:second=models.prepare_4b(self.manifest,'Auto',root)
        download.assert_not_called();self.assertEqual(first,second)

    def test_switch_keeps_both_model_profiles_and_original_weights(self):
        root=self.root/'model'
        with patch.object(models,'download',side_effect=self.download):first=models.prepare_4b(self.manifest,'CPU',root)
        other={**first,'model_name':'Qwen3.5-9B-Q4_K_M','model_file':str(root/'9b.gguf')}
        models.activate(other,root)
        self.assertTrue((root/'profiles/4b.json').exists());self.assertTrue((root/'profiles/9b.json').exists())
        models.activate(first,root)
        self.assertEqual(json.loads((root/'active_model.json').read_text(encoding='utf-8'))['model_name'],'Qwen3-4B-Q4_K_M')
        self.assertTrue(distribution_io.valid(Path(first['model_file']),self.model))

    def test_bad_runtime_archive_and_unknown_backend_are_rejected(self):
        with self.assertRaises(ValueError):models.prepare_4b(self.manifest,'CUDA',self.root/'cuda')
        with zipfile.ZipFile(self.archive,'w') as z:z.writestr('../escape.exe',b'QA')
        with patch.object(models,'download',side_effect=self.download):
            with self.assertRaises(ValueError):models.prepare_4b(self.manifest,'CPU',self.root/'bad')
        self.assertFalse((self.root/'escape.exe').exists())

if __name__=='__main__':unittest.main()
