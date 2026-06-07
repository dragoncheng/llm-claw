#!/usr/bin/env python3
"""WeChat (微信公众号) single-article fetcher for feeds-claw."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from feeds_common import DEFAULT_TIMEOUT, safe_filename, slugify, yaml_quote
from read_wechat_article import WechatArticleFetcher, WechatArticleParser

AD_CLASS_TOKENS = frozenset({
    "ad", "ads", "advert", "advertisement", "promo", "promotion",
    "mpad", "mpcpc", "js_ad", "jsad", "sponsor", "banner",
    "qrcode", "qr_code", "profile_card", "profilecard", "js_jump",
    "reward", "vote_area", "votearea",
})
AD_CLASS_COMPOUND_RE = re.compile(
    r"js_ad|mpcpc|qr[_-]?code|profile[_-]?card|vote_area",
    re.I,
)
AD_URL_RE = re.compile(
    r"(ad\.weixin|wxsnsad|mp\.weixin\.qq\.com/mp/ad|"
    r"advertisement|/promotion/|doubleclick|googlesyndication)",
    re.I,
)
QR_TEXT_RE = re.compile(r"扫码|长按识别|关注公众号|点击关注|阅读原文", re.I)
PROMO_TEXT_RE = re.compile(
    r"想获取|后台私信|微信搜索关注|回复暗号|加群|往期精彩回顾|^END$|萤火AI百宝箱",
    re.I,
)
MIN_IMAGE_PX = 80

CHAPTER_NUM_RE = re.compile(r"^0?\d{1,2}$")
INLINE_HEADING_TAGS = frozenset({"b", "strong", "font"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})
CONTAINER_TAGS = frozenset(
    {"section", "div", "figure", "blockquote", "ul", "ol", "li"}
)


def parse_pub_year(pub_time: str, fallback: str | None = None) -> str:
    if pub_time:
        m = re.search(r"(20\d{2})", pub_time)
        if m:
            return m.group(1)
    return fallback or datetime.now().strftime("%Y")


def parse_pub_date(pub_time: str) -> str:
    if not pub_time:
        return datetime.now().strftime("%Y-%m-%d")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", pub_time)
    if m:
        return m.group(1)
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", pub_time)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    try:
        if pub_time.isdigit() and len(pub_time) >= 10:
            dt = datetime.fromtimestamp(int(pub_time[:10]), tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
    except (ValueError, OSError):
        pass
    return datetime.now().strftime("%Y-%m-%d")


def extract_account(page_html: str, author: str) -> str:
    if author:
        return author.strip()
    soup = BeautifulSoup(page_html, "html.parser")
    node = soup.find(id="js_name")
    if node:
        return node.get_text(" ", strip=True)
    meta = soup.find("meta", attrs={"property": "og:article:author"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    return ""


def _tag_class_tokens(tag: Tag) -> list[str]:
    tokens: list[str] = []
    for cls in tag.get("class") or []:
        tokens.extend(re.split(r"[_-]+", cls.lower()))
    tag_id = (tag.get("id") or "").strip()
    if tag_id:
        tokens.extend(re.split(r"[_-]+", tag_id.lower()))
    return tokens


def tag_has_ad_class(tag: Tag) -> bool:
    if AD_CLASS_TOKENS.intersection(_tag_class_tokens(tag)):
        return True
    marker = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
    return bool(AD_CLASS_COMPOUND_RE.search(marker))


def should_drop_tag(tag: Tag) -> bool:
    if not isinstance(tag, Tag):
        return False
    if tag.name in {"script", "style", "iframe", "svg", "noscript", "form"}:
        return True
    if tag.name and tag.name.startswith("mp-"):
        return True
    if tag_has_ad_class(tag):
        return True
    if tag.get("data-ad") or tag.get("data-card-type") == "ad":
        return True
    return False


def img_dimensions(tag: Tag) -> tuple[int | None, int | None]:
    w = h = None
    for attr in ("data-w", "data-width", "width"):
        val = tag.get(attr)
        if val and str(val).isdigit():
            w = int(val)
            break
    for attr in ("data-h", "data-height", "height"):
        val = tag.get(attr)
        if val and str(val).isdigit():
            h = int(val)
            break
    style = tag.get("style") or ""
    m = re.search(r"width:\s*(\d+)", style)
    if m and w is None:
        w = int(m.group(1))
    m = re.search(r"height:\s*(\d+)", style)
    if m and h is None:
        h = int(m.group(1))
    return w, h


def resolve_img_url(tag: Tag) -> str:
    for attr in ("data-src", "src", "data-original-src", "data-backsrc"):
        val = (tag.get(attr) or "").strip()
        if not val or val.startswith("data:"):
            continue
        if val.startswith("//"):
            return "https:" + val
        return val
    return ""


def is_ad_image(tag: Tag) -> bool:
    if tag.name != "img":
        return False
    if tag_has_ad_class(tag):
        return True
    alt = str(tag.get("alt") or "")
    data_type = str(tag.get("data-type") or "")
    if re.search(r"\bad\b", alt, re.I) or re.search(r"\bad\b", data_type, re.I):
        return True
    url = resolve_img_url(tag)
    if url and AD_URL_RE.search(url):
        return True
    w, h = img_dimensions(tag)
    if w is not None and h is not None and w < MIN_IMAGE_PX and h < MIN_IMAGE_PX:
        return True
    parent = tag.parent
    for _ in range(4):
        if not isinstance(parent, Tag):
            break
        if tag_has_ad_class(parent):
            return True
        parent = parent.parent
    return False


def is_promo_text(text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    if PROMO_TEXT_RE.search(text) and len(text) < 220:
        return True
    if QR_TEXT_RE.search(text) and len(text) < 120:
        return True
    return False


def prune_content_root(root: Tag) -> None:
    for bad in root.find_all(should_drop_tag):
        bad.decompose()
    for block in list(root.find_all("section")):
        text = block.get_text(" ", strip=True)
        if not text and block.find("img"):
            continue
        if is_promo_text(text) and len(text) < 260:
            block.decompose()
            continue
        if text.strip() in {"END", "➤  往期精彩回顾", "往期精彩回顾"}:
            block.decompose()
    blocks = [c for c in root.children if isinstance(c, Tag)]
    for block in reversed(blocks[-5:]):
        text = block.get_text(" ", strip=True)
        imgs = block.find_all("img")
        if is_promo_text(text):
            block.decompose()
            continue
        if len(imgs) == 1 and len(text) < 40 and is_ad_image(imgs[0]):
            block.decompose()


def inline_text(tag: Tag) -> str:
    parts: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name in {"strong", "b"}:
                inner = inline_text(child).strip()
                parts.append(f"**{inner}**" if inner else "")
            elif child.name in {"em", "i"}:
                inner = inline_text(child).strip()
                parts.append(f"*{inner}*" if inner else "")
            elif child.name == "br":
                parts.append("\n")
            elif child.name == "a":
                label = inline_text(child).strip()
                href = (child.get("href") or "").strip()
                if label and href and not AD_URL_RE.search(href):
                    parts.append(f"[{label}]({href})")
                elif label:
                    parts.append(label)
            elif child.name == "span":
                parts.append(inline_text(child))
            else:
                parts.append(child.get_text("", strip=False))
    return html.unescape("".join(parts))


def extract_bg_image_url(tag: Tag) -> str:
    style = tag.get("style") or ""
    m = re.search(r"""background-image:\s*url\(\s*['"]?([^'")]+)""", style, re.I)
    if not m:
        return ""
    url = m.group(1).strip()
    if url.startswith("//"):
        return "https:" + url
    return url


def paragraph_text(p: Tag) -> str:
    parts: list[str] = []
    for child in p.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name != "img":
            parts.append(inline_text(child))
    return html.unescape(re.sub(r"\s+", " ", "".join(parts))).strip()


def guess_ext(url: str, tag: Tag | None = None) -> str:
    path = urlparse(url).path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        if path.endswith(ext):
            return ext
    if tag is not None:
        data_type = (tag.get("data-type") or "").lower()
        if "png" in data_type:
            return ".png"
        if "gif" in data_type:
            return ".gif"
        if "webp" in data_type:
            return ".webp"
    return ".jpg"


def ext_from_content_type(ctype: str) -> str | None:
    ctype = (ctype or "").lower()
    if "png" in ctype:
        return ".png"
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    if "gif" in ctype:
        return ".gif"
    if "webp" in ctype:
        return ".webp"
    return None


def find_existing_image(stem_path: Path) -> Path | None:
    if stem_path.exists() and stem_path.stat().st_size > 0:
        return stem_path
    for ext in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
        alt = stem_path.with_suffix(ext)
        if alt.exists() and alt.stat().st_size > 0:
            return alt
    return None


def download_image(fetcher: WechatArticleFetcher, url: str, dest: Path) -> Path | None:
    existing = find_existing_image(dest)
    if existing:
        return existing
    for _ in range(3):
        try:
            resp = fetcher.session.get(url, timeout=fetcher.timeout)
            if resp.status_code != 200 or not resp.content:
                continue
            actual = dest
            ctype_ext = ext_from_content_type(resp.headers.get("content-type") or "")
            if ctype_ext and actual.suffix != ctype_ext:
                actual = actual.with_suffix(ctype_ext)
            actual.parent.mkdir(parents=True, exist_ok=True)
            actual.write_bytes(resp.content)
            return actual
        except Exception:
            continue
    return None


def render_image_markdown(
    img: Tag,
    *,
    fetcher: WechatArticleFetcher,
    assets_dir: Path,
    vault: Path,
    image_counter: list[int],
) -> str:
    if is_ad_image(img):
        return ""
    url = resolve_img_url(img)
    if not url:
        return ""
    ext = guess_ext(url, img)
    dest = assets_dir / f"{image_counter[0] + 1:02d}{ext}"
    saved = download_image(fetcher, url, dest)
    if saved:
        image_counter[0] += 1
        rel = saved.relative_to(vault).as_posix()
        return f"\n\n![[{rel}]]\n\n"
    return ""


def is_chapter_title_text(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 6:
        return False
    if CHAPTER_NUM_RE.match(text):
        return False
    if re.match(r"^\d+\.\s", text):
        return False
    return True


def merge_chapter_blocks(blocks):
    merged = []
    items = list(blocks)
    i = 0
    while i < len(items):
        block = items[i]
        if block[0] == "text" and CHAPTER_NUM_RE.match(block[1].strip()):
            num = block[1].strip()
            j = i + 1
            while j < len(items) and items[j][0] in {"img", "bg"}:
                j += 1
            if j < len(items):
                nxt = items[j]
                title = ""
                if nxt[0] == "heading":
                    title = nxt[2].strip()
                elif nxt[0] == "text" and is_chapter_title_text(nxt[1]):
                    title = nxt[1].strip()
                if title:
                    merged.append(("heading", "h3", f"{num} {title}"))
                    i = j + 1
                    continue
        merged.append(block)
        i += 1
    return merged


def linear_content_blocks(root: Tag):
    queue: list[Tag | NavigableString] = list(root.children)
    while queue:
        node = queue.pop(0)
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text and not is_promo_text(text):
                yield ("text", text)
            continue
        if not isinstance(node, Tag) or should_drop_tag(node):
            continue

        bg_url = extract_bg_image_url(node)
        if bg_url and node.name in {"section", "div"}:
            yield ("bg", bg_url, node)

        if node.name == "img":
            yield ("img", node)
            continue

        if node.name in HEADING_TAGS:
            text = node.get_text(" ", strip=True)
            if text and not is_promo_text(text):
                yield ("heading", node.name, text)
            continue

        if node.name == "p":
            text = paragraph_text(node)
            if text and not is_promo_text(text):
                yield ("text", text)
            for img in node.find_all("img"):
                yield ("img", img)
            continue

        if node.name == "span":
            text = inline_text(node).strip()
            if text and not is_promo_text(text):
                yield ("text", text)
            continue

        if node.name in INLINE_HEADING_TAGS:
            text = inline_text(node).strip()
            if text and not is_promo_text(text):
                yield ("heading", "h3", text)
            continue

        if node.name in CONTAINER_TAGS:
            queue[:0] = list(node.children)
            continue

        text = inline_text(node).strip()
        if text and not is_promo_text(text) and len(text) > 8:
            yield ("text", text)


def content_to_markdown(
    content_root: Tag,
    *,
    fetcher: WechatArticleFetcher,
    assets_dir: Path,
    vault: Path,
) -> tuple[str, int]:
    image_counter = [0]
    parts: list[str] = []
    seen_img_urls: set[str] = set()

    for block in merge_chapter_blocks(linear_content_blocks(content_root)):
        if block[0] == "heading":
            _, tag, text = block
            level = int(tag[1])
            parts.append(f"\n\n{'#' * level} {text}\n\n")
        elif block[0] == "text":
            parts.append(f"\n\n{block[1]}\n\n")
        elif block[0] == "img":
            img = block[1]
            url = resolve_img_url(img)
            if url in seen_img_urls:
                continue
            md = render_image_markdown(
                img,
                fetcher=fetcher,
                assets_dir=assets_dir,
                vault=vault,
                image_counter=image_counter,
            )
            if md:
                seen_img_urls.add(url)
                parts.append(md)
        elif block[0] == "bg":
            url, _el = block[1], block[2]
            if url in seen_img_urls or AD_URL_RE.search(url):
                continue
            ext = guess_ext(url)
            dest = assets_dir / f"{image_counter[0] + 1:02d}{ext}"
            saved = download_image(fetcher, url, dest)
            if saved:
                image_counter[0] += 1
                seen_img_urls.add(url)
                rel = saved.relative_to(vault).as_posix()
                parts.append(f"\n\n![[{rel}]]\n\n")

    body = re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()
    return body, image_counter[0]


def build_markdown(
    *,
    title: str,
    account: str,
    author: str,
    pub_date: str,
    fetched: str,
    url: str,
    tags: list[str],
    body: str,
) -> str:
    tag_set = ["feeds", "wechat"]
    for t in tags:
        t = t.strip()
        if t and t not in tag_set:
            tag_set.append(t)
    tag_yaml = ", ".join(tag_set)
    lines = [
        "---",
        "source: wechat",
        "platform: wechat",
        f"account: {yaml_quote(account)}",
        f"author: {yaml_quote(author)}",
        f"published: {pub_date}",
        f"url: {yaml_quote(url)}",
        f"fetched: {fetched}",
        f"tags: [{tag_yaml}]",
        f"created: {fetched}",
        "---",
        "",
        f"# {title}",
        "",
        "## 元信息",
        "",
        f"- **公众号**：{account or '—'}",
        f"- **作者**：{author or '—'}",
        f"- **原文链接**：{url}",
        f"- **抓取日期**：{fetched}",
        "",
        "## 正文",
        "",
        body,
        "",
    ]
    return "\n".join(lines)


def save_wechat(
    url: str,
    vault: Path,
    tags: list[str],
    *,
    dry_run: bool = False,
    force: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    fetcher = WechatArticleFetcher(timeout=timeout)
    fetched = fetcher.fetch(url)
    if "error" in fetched:
        return fetched

    parser = WechatArticleParser()
    meta = parser.parse(fetched["page_html"])
    if not meta.get("title") and not meta.get("content"):
        return {
            "error": "no_content",
            "message": "Could not parse article content.",
            "source_url": fetched["source_url"],
        }

    soup = BeautifulSoup(fetched["page_html"], "html.parser")
    content_root = soup.find(id="js_content")
    if not content_root:
        return {
            "error": "no_content",
            "message": "Missing #js_content in page.",
            "source_url": fetched["source_url"],
        }

    prune_content_root(content_root)

    title = meta["title"] or "wechat-article"
    account = extract_account(fetched["page_html"], meta.get("author", ""))
    author = meta.get("author") or account
    pub_date = parse_pub_date(meta.get("pub_time", ""))
    year = parse_pub_year(meta.get("pub_time", ""))
    fetched_date = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(title)

    md_dir = vault / "01_mydoc" / "14_feeds" / year
    assets_dir = vault / "_assets" / "images" / "14_feeds" / "wechat" / slug
    md_path = md_dir / safe_filename(title)

    if md_path.exists() and not dry_run and not force:
        stem = md_path.stem
        md_path = md_dir / f"{stem}-{datetime.now().strftime('%H%M%S')}.md"

    if force and assets_dir.exists() and not dry_run:
        for old in assets_dir.glob("*"):
            if old.is_file():
                old.unlink()

    body, image_count = content_to_markdown(
        content_root,
        fetcher=fetcher,
        assets_dir=assets_dir,
        vault=vault,
    )

    if not body:
        return {
            "error": "no_content",
            "message": "Content empty after ad filtering.",
            "source_url": fetched["source_url"],
            "title": title,
        }

    md_text = build_markdown(
        title=title,
        account=account,
        author=author,
        pub_date=pub_date,
        fetched=fetched_date,
        url=fetched["source_url"],
        tags=tags,
        body=body,
    )

    result = {
        "title": title,
        "account": account,
        "source_url": fetched["source_url"],
        "md_path": str(md_path.relative_to(vault)),
        "assets_dir": str(assets_dir.relative_to(vault)),
        "images": image_count,
        "chars": len(body),
        "dry_run": dry_run,
        "tool": "feeds-claw/fetch_wechat",
    }

    if dry_run:
        return result

    md_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_text, encoding="utf-8")
    return result
