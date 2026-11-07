"""Offline shim tests using a fake executable; never call a real model."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="exp7-catalog-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "real-codex"
        self.binary.write_text(
            f"#!{sys.executable}\n"
            "import json,os,pathlib,sys\n"
            "if sys.argv[1:] == ['--version'] or sys.argv[1:] == ['-V']:\n"
            f" print({catalog.EXPECTED_VERSION!r})\n"
            "elif 'debug' in sys.argv:\n"
            " path=json.loads(sys.argv[2].split('=',1)[1])\n"
            " print(pathlib.Path(path).read_text())\n"
            "else:\n"
            " print(json.dumps({'argv':sys.argv[1:],'stdin':sys.stdin.read(),"
            "'sentinel':os.environ.get('CATALOG_TEST_SENTINEL')}))\n")
        self.binary.chmod(0o700)
        self.models = [{"slug": "test-model", "base_instructions": "unchanged", "supports_parallel_tool_calls": True},
                       {"slug": "other-model", "base_instructions": "also unchanged"}]
        self.cache = self.root / "models_cache.json"
        self.cache.write_text(json.dumps({"models": self.models, "client_version": "0.159.0",
                                          "fetched_at": "2026-11-07T14:30:58Z", "identity": "private-identity"}))
        self.runtime = self.root / "catalog-runtime.py"
        self.runtime.write_bytes(Path(catalog.__file__).read_bytes())
        with patch.object(catalog, "__file__", str(self.runtime)):
            self.receipt = catalog.prepare_install(self.cache, self.root / "profile", self.binary, ["test-model"])
        self.manifest_path = Path(self.receipt["manifest"])
        self.manifest = json.loads(self.manifest_path.read_text())
        self.argv = ["exec", "--ignore-user-config", "--ignore-rules", "--json",
                     "--model", "test-model", "-c", 'model_reasoning_effort="high"', "-"]

    def run_shim(self, argv=None, text=""):
        return subprocess.run([self.receipt["shim"], *(self.argv if argv is None else argv)],
                              input=text, capture_output=True, text=True, timeout=10,
                              env={**os.environ, "CATALOG_TEST_SENTINEL": "private-environment-value"})

    def test_install_preserves_all_model_objects_and_excludes_identity(self):
        self.assertEqual(json.loads(Path(self.manifest["catalog_path"]).read_text()), {"models": self.models})
        self.assertNotIn("private-identity", self.manifest_path.read_text())
        self.assertFalse(self.receipt["path_activated"])
        self.assertEqual(self.manifest["binary_sha256"], catalog.sha(self.binary))

    def test_exec_and_resume_preserve_original_arguments_stdin_and_environment(self):
        for argv in (self.argv, ["exec", "resume", *self.argv[1:-1], "private-session-id", "-"]):
            with self.subTest(resume="resume" in argv):
                result = self.run_shim(argv, "private original prompt\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data["argv"][2:], argv)
                self.assertEqual(data["argv"][:2], ["-c", "model_catalog_json="+json.dumps(self.manifest["catalog_path"])])
                self.assertEqual(data["stdin"], "private original prompt\n")
                self.assertEqual(data["sentinel"], "private-environment-value")
        journal = Path(self.manifest["invocation_audit"]).read_text()
        self.assertEqual(len(journal.splitlines()), 2)
        for private in ("private-session-id", "private original prompt", "private-environment-value"):
            self.assertNotIn(private, journal)

    def test_version_passes_through_without_invocation_or_catalog_override(self):
        result = self.run_shim(["--version"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), catalog.EXPECTED_VERSION)
        self.assertFalse(Path(self.manifest["invocation_audit"]).exists())

    def test_catalog_manifest_runtime_and_binary_changes_fail_before_dispatch(self):
        for path in (Path(self.manifest["catalog_path"]), self.manifest_path, self.runtime, self.binary):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original+b" ")
                result = self.run_shim()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertFalse(Path(self.manifest["invocation_audit"]).exists())
                path.write_bytes(original)
                # Restoring bytes still changes ctime and must fail for binary;
                # test it last rather than silently accepting repaired metadata.

    def test_unknown_model_extra_override_and_nonstudy_commands_are_blocked(self):
        invalid = [["login"], ["exec", "review", *self.argv[1:]],
                   [*self.argv[:-1], "-c", 'model_catalog_json="other.json"', "-"],
                   ["other-model" if x == "test-model" else x for x in self.argv],
                   [x for x in self.argv if x != "--ignore-user-config"]]
        for argv in invalid:
            with self.subTest(argv=argv):
                result = self.run_shim(argv)
                self.assertEqual(result.returncode, 78)
                self.assertEqual(result.stdout, "")
        self.assertFalse(Path(self.manifest["invocation_audit"]).exists())

    def test_per_invocation_binary_guard_avoids_rehashing_large_binary(self):
        with patch.object(catalog, "sha", wraps=catalog.sha) as digest:
            catalog.verify_install(self.manifest_path, self.receipt["manifest_sha256"])
            self.assertNotIn(self.binary, [Path(c.args[0]) for c in digest.call_args_list])
        with patch.object(catalog, "sha", wraps=catalog.sha) as digest:
            catalog.verify_install(self.manifest_path, self.receipt["manifest_sha256"], rehash_binary=True)
            self.assertIn(self.binary, [Path(c.args[0]) for c in digest.call_args_list])

    def test_failed_audit_prevents_exec_and_redacts_details(self):
        with patch.object(catalog, "audit_invocation", side_effect=OSError("private failure detail")), \
             patch.object(catalog.os, "execv") as execute, \
             patch.object(catalog.sys.stderr, "write") as error:
            self.assertEqual(catalog.shim_main(self.manifest_path, self.receipt["manifest_sha256"], self.argv), 78)
            execute.assert_not_called()
            self.assertNotIn("private failure detail", error.call_args.args[0])

    def test_concurrent_audit_writes_remain_complete_json_lines(self):
        effective, _ = catalog.command_for(self.manifest, self.argv)
        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(lambda _: catalog.audit_invocation(self.manifest, self.receipt["manifest_sha256"],
                                                             self.argv, effective), range(30)))
        records = [json.loads(line) for line in Path(self.manifest["invocation_audit"]).read_text().splitlines()]
        self.assertEqual(len(records), 30)
        self.assertTrue(all(r["catalog_sha256"] == self.manifest["catalog_sha256"] for r in records))

    def test_debug_validation_is_noninference_and_requires_exact_catalog(self):
        result = catalog.validate_debug(self.manifest_path, self.receipt["manifest_sha256"])
        self.assertTrue(result["exact_model_catalog_equal"])
        self.assertEqual(result["new_model_calls"], 0)
        self.assertFalse(Path(self.manifest["invocation_audit"]).exists())
        changed = subprocess.CompletedProcess([], 0, '{"models": []}', '')
        with patch.object(catalog.subprocess, "run", return_value=changed):
            with self.assertRaises(catalog.CatalogError):
                catalog.validate_debug(self.manifest_path, self.receipt["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
