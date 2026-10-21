import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/verify_signature.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Authenticode policy")


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell(command):
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True)


@pytest.mark.parametrize("change", [
    "$signature.Status='NotSigned'",
    "$signature.Status='HashMismatch'",
    "$signature.SignatureType='Catalog'",
    "$certificate.Publisher='Unapproved publisher'",
    "$certificate.Email='private@example.invalid'",
    "$signature.TimeStamperCertificate=$null",
    "$certificate.Extensions=@()",
])
def test_signed_release_policy_rejects_invalid_or_private_identity(change):
    command = f"""
    . {ps_quote(SCRIPT)}
    $certificate=[pscustomobject]@{{Publisher='SignPath Foundation';Email='';Extensions=@(
        [pscustomobject]@{{Oid=[pscustomobject]@{{Value='2.5.29.37'}};
        EnhancedKeyUsages=@([pscustomobject]@{{Value='1.3.6.1.5.5.7.3.3'}})}})}}
    $certificate | Add-Member ScriptMethod GetNameInfo {{
        param($kind,$issuer)
        if ([string]$kind -eq 'EmailName') {{return $this.Email}} else {{return $this.Publisher}}
    }}
    $signature=[pscustomobject]@{{Status='Valid';SignatureType='Authenticode';
        SignerCertificate=$certificate;TimeStamperCertificate=[pscustomobject]@{{}}}}
    {change}
    try {{ Assert-SigningPolicy $signature 'SignPath Foundation'; exit 0 }} catch {{ exit 9 }}
    """
    assert powershell(command).returncode == 9


def test_actual_unsigned_file_cannot_pass_as_signed_release(tmp_path):
    file = tmp_path / "unsigned.exe"
    file.write_bytes(b"MZ unsigned fixture")
    result = powershell(f"& {ps_quote(SCRIPT)} -Path {ps_quote(file)}")
    assert result.returncode == 1
    assert '"status":"Valid"' not in result.stdout


def test_required_signing_stops_before_build_when_no_signer_is_configured():
    build = SCRIPT.with_name("bootstrap_build.ps1")
    result = powershell(f"& {ps_quote(build)} -RequireSigning")
    assert result.returncode != 0
    assert "Signed build requires an approved signing command" in result.stderr


@pytest.mark.skipif(not os.environ.get("OBS_SIGNED_TEST_FILE"), reason="Optional signed vendor fixture")
def test_windows_verifies_real_signature_and_rejects_unexpected_publisher():
    file = Path(os.environ["OBS_SIGNED_TEST_FILE"])
    good = powershell(f"& {ps_quote(SCRIPT)} -Path {ps_quote(file)} -ExpectedPublisher 'Pyrsys B.V.'")
    assert good.returncode == 0, good.stderr
    assert '"status":"Valid"' in good.stdout
    wrong = powershell(f"& {ps_quote(SCRIPT)} -Path {ps_quote(file)}")
    assert wrong.returncode == 1
    assert "Pyrsys" not in wrong.stdout + wrong.stderr
    for metadata in ["-ExpectedProduct 'Wrong product'", "-ExpectedVersion '0.0.0'"]:
        invalid = powershell(f"& {ps_quote(SCRIPT)} -Path {ps_quote(file)} "
                             f"-ExpectedPublisher 'Pyrsys B.V.' {metadata}")
        assert invalid.returncode == 1
        assert "Unexpected product" in invalid.stderr


@pytest.mark.skipif(not os.environ.get("OBS_SIGNED_TEST_FILE"), reason="Optional signed vendor fixture")
def test_windows_rejects_a_modified_signed_binary(tmp_path):
    original = Path(os.environ["OBS_SIGNED_TEST_FILE"])
    content = bytearray(original.read_bytes())
    content[1024] ^= 1
    changed = tmp_path / "changed.exe"
    changed.write_bytes(content)
    result = powershell(f"& {ps_quote(SCRIPT)} -Path {ps_quote(changed)} -ExpectedPublisher 'Pyrsys B.V.'")
    assert result.returncode == 1
