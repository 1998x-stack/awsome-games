"""Separate model labels from prompt visibility without promoting source metadata to fact."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from research_pipeline import split_model_and_prompt


class ResearchClaimSemanticsTests(unittest.TestCase):
    def test_prompt_only_has_no_model_identity(self):
        model,prompt=split_model_and_prompt("prompt not shared","未发现公开提示词")
        self.assertIsNone(model)
        self.assertEqual(prompt,"INDEX_REPORTS_NOT_SHARED")
        model,prompt=split_model_and_prompt("prompt shared (text not in index)","未发现公开提示词")
        self.assertIsNone(model)
        self.assertEqual(prompt,"INDEX_CLAIMS_SHARED_TEXT_NOT_CAPTURED")

    def test_mixed_field_separates_model_from_prompt(self):
        model,prompt=split_model_and_prompt("Claude Fable 5.2 / prompt not shared","未发现公开提示词")
        self.assertEqual(model,"Claude Fable 5.2")
        self.assertEqual(prompt,"INDEX_REPORTS_NOT_SHARED")
        model,prompt=split_model_and_prompt("Claude Fable 5.2","未发现公开提示词")
        self.assertEqual(model,"Claude Fable 5.2")
        self.assertEqual(prompt,"NOT_LOCATED")

    def test_unknown_remains_unknown(self):
        self.assertEqual(split_model_and_prompt("not checked",None),(None,"NOT_VERIFIED"))


if __name__=="__main__":
    unittest.main()
