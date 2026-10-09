"""Download HistData.com M1 bid bars (ASCII) as yearly zips. Personal research use.

Usage: python scripts/fetch_histdata.py EURUSD 2020 2025 data/raw/histdata
Data is UNTRUSTED input: only parsed as text/CSV, never executed.
"""
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

BASE = "https://www.histdata.com"
UA = {"User-Agent": "Mozilla/5.0 (research; fxlab)"}


def fetch(pair: str, year: int, out: Path) -> Path:
    page = f"{BASE}/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair.lower()}/{year}"
    r = requests.get(page, headers=UA, timeout=30)
    r.raise_for_status()
    tk = re.search(r'name="tk" id="tk" value="([0-9a-f]+)"', r.text)
    if not tk:
        raise RuntimeError(f"no token on page for {pair} {year}")
    form = {"tk": tk.group(1), "date": str(year), "datemonth": str(year),
            "platform": "ASCII", "timeframe": "M1", "fxpair": pair.upper()}
    dest = out / f"HISTDATA_COM_ASCII_{pair.upper()}_M1_{year}.zip"
    with requests.post(f"{BASE}/get.php", data=form, headers={**UA, "Referer": page}, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        size = int(resp.headers.get("Content-Length", 0))
        print(f"{year}: Content-Length {size/1e6:.1f} MB", flush=True)
        if size > 200e6:
            raise RuntimeError("unexpectedly large; aborting")
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1 << 20):
                f.write(chunk)
    if not zipfile.is_zipfile(dest):
        raise RuntimeError(f"{dest} is not a zip")
    return dest


if __name__ == "__main__":
    pair, y0, y1, outdir = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
    outdir.mkdir(parents=True, exist_ok=True)
    for y in range(y0, y1 + 1):
        p = fetch(pair, y, outdir)
        print("saved", p.name, f"{p.stat().st_size/1e6:.1f} MB", flush=True)
        time.sleep(2)
