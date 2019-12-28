import requests


def get_variants(stream_url):
    resp = requests.get(stream_url)
    master_pls = resp.text
    variant_urls = [line for line in master_pls.splitlines() if line.startswith("http")]
    return {
        ("450p", "720p")["720" in url]: requests.get(url).text for url in variant_urls
    }


def get_angle_playlists(variant_pls):
    def find_startswith(lines, s, rev=False):
        lines = enumerate(lines)
        if rev:
            lines = reversed(tuple(lines))
        for i, line in lines:
            if line.startswith(s):
                return i

    pls = variant_pls.splitlines()
    headers_end = find_startswith(pls, "#EXT-X-KEY")
    headers = pls[:headers_end]
    angle1_end = find_startswith(pls, "#EXT-X-DISCONTINUITY") + 2
    angle1 = pls[:angle1_end] + ["#EXT-X-ENDLIST", ""]

    angle2 = pls[angle1_end + 1:]
    if not angle2[0].startswith("#EXT-X-KEY"):
        last_key = find_startswith(angle1, "#EXT-X-KEY", rev=True)
        angle2.insert(0, angle1[last_key])
    angle2 = headers + angle2
    return {1: "\n".join(angle1), 2: "\n".join(angle2)}


def store_playlists(stream_url):
    variants = get_variants(stream_url)

    for angle, pls in get_angle_playlists(variants["720p"]).items():
        with open(f"s1{angle}.m3u8", "w") as f:
            f.write(pls)
