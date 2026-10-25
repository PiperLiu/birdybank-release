import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "upload_release_assets", Path(__file__).with_name("upload-release-assets.py")
)
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


class ReleaseAssetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.version = "1.3.2"
        self.expected = {
            "BirdyBank_1.3.2_aarch64.dmg.zip": "a" * 64,
            "BirdyBank_1.3.2_x64.dmg.zip": "b" * 64,
            "BirdyBank_1.3.2_x64-setup.exe.zip": "c" * 64,
        }
        self.notes = "\n".join(f"{digest}  {name}" for name, digest in self.expected.items())
        self.data = {"tagName": self.version, "body": self.notes, "assets": []}

    def read(self):
        with patch.object(upload.subprocess, "check_output", return_value=json.dumps(self.data)):
            return upload.release(self.version, self.notes, self.expected)

    def test_manifest_requires_each_platform_exactly_once(self):
        self.assertEqual(upload.expected_assets(self.notes, self.version), self.expected)
        first = self.notes.splitlines()[0]
        for text in ["\n".join(self.notes.splitlines()[1:]), self.notes + "\n" + first]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                upload.expected_assets(text, self.version)

    def test_manifest_rejects_foreign_names_paths_and_invalid_hashes(self):
        for text in [
            self.notes.replace("aarch64.dmg.zip", "../aarch64.dmg.zip"),
            self.notes.replace("aarch64.dmg.zip", "unexpected.zip"),
            self.notes.replace("a" * 64, "invalid"),
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                upload.expected_assets(text, self.version)

    def test_matching_existing_assets_can_be_reused(self):
        for name, digest in self.expected.items():
            self.data["assets"].append(
                {"name": name, "digest": "sha256:" + digest, "state": "uploaded", "size": 123}
            )
        self.assertEqual(set(self.read()), set(self.expected))

    def test_incomplete_or_different_assets_are_not_overwritten(self):
        name, digest = next(iter(self.expected.items()))
        valid = {"name": name, "digest": "sha256:" + digest, "state": "uploaded", "size": 123}
        for changes in [{"state": "starter"}, {"digest": "sha256:" + "0" * 64}, {"size": 0}]:
            self.data["assets"] = [{**valid, **changes}]
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.read()

    def test_changed_notes_or_tag_block_upload(self):
        for field in ["body", "tagName"]:
            original = self.data[field]
            self.data[field] = "different"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.read()
            self.data[field] = original

    def test_unexpected_existing_asset_blocks_upload(self):
        self.data["assets"] = [{"name": "unreviewed.zip"}]
        with self.assertRaises(ValueError):
            self.read()


if __name__ == "__main__":
    unittest.main()
