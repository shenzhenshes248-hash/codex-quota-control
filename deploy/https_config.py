"""Validate the domain/public IP and render the matching Caddy configuration."""
import argparse
import ipaddress
from pathlib import Path
import re


def normalize_host(value: str) -> str:
    host = value.strip()
    if host.startswith("[") and host.endswith("]"):
        if ":" not in host:
            raise ValueError("方括号仅适用于 IPv6 地址")
        host = host[1:-1]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if (len(host) > 253 or "." not in host or re.fullmatch(r"[0-9.]+", host)
                or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                           for label in host.split("."))):
            raise ValueError("请输入域名或公网 IP，不要包含 https://、端口或路径") from None
        return host.lower()
    if not address.is_global or address.is_multicast or "%" in host:
        raise ValueError("IP 直连需要固定公网 IP，不能使用内网、回环或保留地址")
    return str(address)


def endpoint(host: str) -> str:
    host = normalize_host(host)
    return "https://" + (f"[{host}]" if ":" in host else host) + ":8443"


def render_config(template: str, host: str) -> str:
    host = normalize_host(host)
    text = template.replace("https://api.example.com:8443", endpoint(host))
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return text
    # IP connections commonly omit TLS SNI. Select this IP's certificate explicitly.
    text = text.replace("    admin off\n", f"    admin off\n    default_sni {host}\n")
    return text.replace(
        "        issuer acme {\n",
        "        issuer acme https://acme-v02.api.letsencrypt.org/directory {\n"
        "            profile shortlived\n",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成域名或公网 IP 的 HTTPS 配置")
    parser.add_argument("host")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--url", action="store_true")
    mode.add_argument("--template", type=Path)
    args = parser.parse_args()
    try:
        host = normalize_host(args.host)
    except ValueError as error:
        parser.error(str(error))
    if args.template:
        print(render_config(args.template.read_text(encoding="utf-8"), host), end="")
    else:
        print(endpoint(host) if args.url else host)
