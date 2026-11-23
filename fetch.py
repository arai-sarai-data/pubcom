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


def parse(html):
    """一覧の1件ずつ：案件名・案件番号・案の公示日・結果の公示日・提出意見数・所管省庁。"""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    items = []
    for blk in re.split(r"<li[ >]", text)[1:]:
        t = re.sub(r"<[^>]+>", "\n", blk)
        t = re.sub(r"[ \t　]+", " ", t)
        lines = [x.strip() for x in t.split("\n") if x.strip()]
        joined = " ".join(lines)
        no = re.search(r"案件番号\s*(\d{9})", joined)
        if not no:
            continue
        m = re.search(r'href="([^"]*?(?:CLASSNAME=PCMMSTDETAIL|/pcm/detail)[^"]*)"', blk)
        title = next((x for x in lines if len(x) > 12 and not re.match(r"(案件番号|結果|案の|提出|所管|受付|NEW|募集)", x)), "")
        cnt = re.search(r"提出意見数\s*([\d,]+)", joined)
        org = re.search(r"所管省庁\s*(\S+)", joined)
        items.append({"no": no.group(1), "title": title, "url": (BASE + m.group(1).replace("&amp;", "&")) if m else "",
                      "plan": jdate((re.search(r"案の公示日\s*(\S+)", joined) or [None, ""])[1]),
                      "result": jdate((re.search(r"結果の公示日\s*(\S+)", joined) or [None, ""])[1]),
                      "n": int(cnt.group(1).replace(",", "")) if cnt else None, "org": org.group(1) if org else ""})
    return items


def run():
    seen = {}
    for itype in ("2", "3"):  # 結果公示案件・過去案件（画面のタブの順）
        empty = 0
        for page in range(1, MAX_PAGES + 1):
            html = oc.decode(oc.get(LIST, params={"indexType": itype, "pageNo": page, "pageSize": 100, "sortType": 1},
                                    cache="pcm_%s_%d.html" % (itype, page)))
            items = [x for x in parse(html) if x["n"] is not None]
            new = [x for x in items if x["no"] not in seen]
            for x in new:
                seen[x["no"]] = x
            oc.log("type", itype, "page", page, "items", len(items), "new", len(new), "total", len(seen))
            empty = empty + 1 if not new else 0
            if empty >= 2:
                break
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
            "意見公募をしなかった理由の公示（提出意見数0）も一覧に含まれます。意見の数は、案に対する関心の高さや周知の度合いで大きく変わります。")
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
