"""パブコメは聞かれているか：e-Govパブリック・コメントの結果公示・過去案件の一覧から、
提出意見が0件の案件の割合、意見が多かった案件、案から結果までの日数を府省ごとに並べる。"""
import re
from collections import defaultdict
import datetime as dt

from lib import oc

BASE = "https://public-comment.e-gov.go.jp"
LIST = BASE + "/pcm/list"
MAX_PAGES = int(__import__("os").environ.get("PCM_MAX_PAGES", "400"))


def jdate(s):
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s or "")
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def post_list(mode, page):
    """一覧はフォームのPOSTでページ送りする（Mode 1=結果公示案件 / 2=過去案件、1ページ100件）。
    sortItem=1（公示日順）。0にすると意見数「－」の案件が先に並び、意見数が読めない。"""
    import json as _j
    cache = oc.RAW / "cache" / ("pcm_s1_%d_%d.html" % (mode, page))
    if cache.exists() and cache.stat().st_size > 1000 and page > 3:
        return cache.read_text(encoding="utf-8")
    data = {"CLASSNAME": "PCMMSTLIST", "Page": str(page), "Mode": str(mode), "Type": "0", "bMode": "1",
            "sortItem": "1", "sortButton": "1", "dspcnt": "100", "keywordOr": "0"}
    err = None
    for i in range(4):
        oc._polite(LIST)
        try:
            r = oc._session.post(LIST, data=data, timeout=120)
            r.raise_for_status()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text, encoding="utf-8")
            return r.text
        except Exception as e:
            err = e
    raise oc.DataError("一覧の取得に失敗: Mode=%d Page=%d (%s)" % (mode, page, err))


def cell(blk, label):
    m = re.search(label + r"</span>\s*(?:<span>)?([^<]*)", blk)
    return m.group(1).strip() if m else ""


def parse(html):
    items = []
    for blk in re.split(r'<li class="egovui-flex-column">', html)[1:]:
        no = cell(blk, "案件番号")
        if not re.fullmatch(r"\d{9}", no):
            continue
        t = re.search(r'<h2[^>]*>\s*<a[^>]*>(.*?)</a>', blk, re.S)
        mode = re.search(r"id=(\d+)&amp;Mode=(\d)", blk)
        n = cell(blk, "提出意見数").replace(",", "")
        items.append({"no": no, "title": re.sub(r"\s+", " ", t.group(1)).strip() if t else "",
                      "url": (BASE + "/pcm/1040?CLASSNAME=PCM1040&id=%s&Mode=%s" % mode.groups()) if mode else "",
                      "plan": jdate(cell(blk, "案の公示日")), "result": jdate(cell(blk, "結果の公示日")),
                      "n": int(n) if n.isdigit() else None, "org": cell(blk, "所管省庁")})
    return items


def run():
    seen, held_none = {}, 0
    for mode in (1, 2):
        first = post_list(mode, 1)
        tot = re.search(r"/\s*(\d+)\s*</", re.sub(r"\s+", " ", first))
        last = re.findall(r'id="totalPage" value="(\d+)"', first) or re.findall(r'name="totalPage" value="(\d+)"', first)
        pages = int(last[0]) if last else MAX_PAGES
        oc.log("mode", mode, "pages", pages)
        for page in range(1, min(pages, MAX_PAGES) + 1):
            items = parse(first if page == 1 else post_list(mode, page))
            if not items:
                break
            for x in items:
                if x["n"] is None:
                    held_none += 1
                    continue          # 「－」＝意見公募を実施しなかった案件などは数えない
                seen.setdefault(x["no"], x)
            if page % 20 == 0:
                oc.log("mode", mode, "page", page, "total", len(seen))
    rows = list(seen.values())
    oc.check(len(rows) > 3000, "パブコメの件数が少なすぎます(%d)。一覧の形式が変わった可能性" % len(rows))
    oc.check(sum(1 for r in rows if r["org"]) > len(rows) * 0.9, "所管省庁が取れていません")
    for r in rows:
        r["days"] = (r["result"] - r["plan"]).days if r["plan"] and r["result"] else None
        r["title_url"] = r["url"]
    by = defaultdict(list)
    for r in rows:
        by[r["org"]].append(r)
    orgs = []
    for k, v in by.items():
        if len(v) < 30:
            continue
        z = sum(1 for r in v if r["n"] == 0)
        orgs.append({"org": k, "zero": z / len(v), "n": len(v), "sum": sum(r["n"] for r in v),
                     "med": sorted(r["n"] for r in v)[len(v) // 2]})
    zero = sorted(orgs, key=lambda r: -r["zero"])
    most = sorted(rows, key=lambda r: -r["n"])
    cols = [{"key": "title", "label": "案件", "type": "link"}, {"key": "n", "label": "提出意見数", "type": "num", "bar": True},
            {"key": "org", "label": "所管省庁"}, {"key": "result", "label": "結果の公示日"}]
    for r in rows:
        r["result"] = r["result"].isoformat() if r["result"] else ""
        r["plan"] = r["plan"].isoformat() if r["plan"] else ""
    meth = ("e-Govパブリック・コメントの「結果公示案件」「過去案件」の一覧に載っている提出意見数をそのまま数えました。"
            "提出意見数が「－」の案件（意見公募を実施しなかった理由の公示など）は数えていません。意見の数は、案に対する関心の高さや周知の度合いで大きく変わります。")
    R = [{"id": "zero", "tab": "意見0件", "title": "提出意見が0件だった案件の割合が高い府省",
          "desc": "パブコメを実施しても、誰からも意見が届かなかった案件の割合（30件以上の府省）。", "rows": zero, "method": meth,
          "columns": [{"key": "org", "label": "府省"}, {"key": "zero", "label": "意見0件の割合", "type": "num", "fmt": "pct", "bar": True},
                      {"key": "n", "label": "案件数", "type": "num"}, {"key": "med", "label": "意見数の中央値", "type": "num"},
                      {"key": "sum", "label": "意見数の合計", "type": "num"}], "share_label": "org", "share_value": "zero"},
         {"id": "most", "tab": "意見が多い", "title": "提出意見が多かったパブコメ", "rows": most, "columns": cols, "method": meth,
          "trend": oc.trend(most, "org", 50, "件", "件"), "share_label": "title", "share_value": "n"}]
    meta = {"data_period": "e-Govに掲載の結果公示・過去案件（%s時点）" % oc.today(),
            "stats": [{"label": "数えたパブコメ", "value": len(rows), "unit": "件"},
                      {"label": "意見0件の割合", "value": sum(1 for r in rows if r["n"] == 0) / len(rows), "fmt": "pct"},
                      {"label": "提出意見の合計", "value": sum(r["n"] for r in rows), "unit": "件"}],
            "sources": [{"name": "e-Govパブリック・コメント（結果公示案件・過去案件）", "org": "デジタル庁・各府省", "url": LIST,
                         "license": "政府標準利用規約（第2.0版）"}]}
    oc.write(meta, R, search=[{"n": r["title"], "s": r["org"], "u": r["url"], "k": [["提出意見数", str(r["n"])], ["結果の公示日", r["result"]]]} for r in rows])


if __name__ == "__main__":
    oc.main(run)
