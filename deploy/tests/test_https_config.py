import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from https_config import endpoint, normalize_host, render_config

TEMPLATE = (Path(__file__).resolve().parents[1] / "Caddyfile.example").read_text(encoding="utf-8")


class HttpsConfigTest(unittest.TestCase):
    def test_domain_preserves_existing_certificate_configuration(self):
        self.assertEqual("api.example.com", normalize_host("API.Example.com"))
        text = render_config(TEMPLATE, "API.Example.com")
        self.assertIn("https://api.example.com:8443 {", text)
        self.assertNotIn("profile shortlived", text)
        self.assertIn("disable_tlsalpn_challenge", text)

    def test_public_ipv4_uses_renewable_public_certificate_without_sni(self):
        text = render_config(TEMPLATE, "38.207.137.194")
        self.assertEqual("https://38.207.137.194:8443", endpoint("38.207.137.194"))
        self.assertIn("default_sni 38.207.137.194", text)
        self.assertIn("issuer acme https://acme-v02.api.letsencrypt.org/directory", text)
        self.assertIn("profile shortlived", text)
        self.assertIn("disable_tlsalpn_challenge", text)
        self.assertNotIn("api.example.com:8443", text)

    def test_ipv6_url_is_bracketed_and_normalized(self):
        self.assertEqual("https://[2606:4700:4700::1111]:8443", endpoint("[2606:4700:4700:0:0:0:0:1111]"))
        text = render_config(TEMPLATE, "2606:4700:4700::1111")
        self.assertIn("https://[2606:4700:4700::1111]:8443 {", text)
        self.assertIn("default_sni 2606:4700:4700::1111", text)

    def test_invalid_or_nonpublic_targets_are_rejected(self):
        for host in ("127.0.0.1", "10.0.0.1", "::1", "224.0.0.1", "192.0.2.1",
                     "999.1.1.1", "api..com", "api.example.com:8443", "https://example.com",
                     "example.com/path", "example.com\nadmin", "[example.com]", "-api.example.com"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    normalize_host(host)


if __name__ == "__main__":
    unittest.main()
