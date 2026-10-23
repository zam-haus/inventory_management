"""
Rendering ZPL with labelary.com (api.labelary.com): previews of ZPL templates in the print dialog and
the fake Zebra printer (simulator.py). An external service with rate limits; it gets the label's ZPL.
No Django here, so the simulator runs without it.
"""
import urllib.request

API = "https://api.labelary.com"
DOTS_PER_MM = {152: 6, 203: 8, 300: 12, 600: 24}


def render(zpl, dpi=203, width_in=2.25, height_in=1.25, count=1, base=API, timeout=30):
    """(bytes, extension): PNG of the first label, or one PDF of `count` labels. Raises OSError (also
    urllib.error.URLError, HTTPError) if labelary cannot be reached or refuses."""
    url = (f"{base.rstrip('/')}/v1/printers/{DOTS_PER_MM.get(dpi, 8)}dpmm/labels/"
           f"{width_in:.2f}x{height_in:.2f}/")
    pdf = count > 1
    request = urllib.request.Request(url if pdf else url + "0/", data=zpl.encode("utf-8"), method="POST",
                                     headers={"Accept": "application/pdf" if pdf else "image/png",
                                              "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), "pdf" if pdf else "png"
