"""Conservative navigation-only allowlist for the user-approved reference pages."""

from urllib.parse import parse_qs, urlsplit

HOSTS = {"google.com", "www.google.com", "baidu.com", "www.baidu.com"}
PATHS = {"google.com": {"/", "/search", "/imghp"}, "baidu.com": {"/", "/s"}}
QUERY_KEYS = {"q", "tbm", "udm", "hl", "start", "source", "wd", "pn", "ie", "tn"}


def safe_navigation(url, origin=None):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or host not in HOSTS
            or parsed.port not in (None, 443)
        ):
            return False
        if parsed.username or parsed.password or parsed.fragment:
            return False
        if origin and urlsplit(origin).netloc.lower() != parsed.netloc.lower():
            return False
        domain = host.removeprefix("www.")
        return (
            parsed.path in PATHS[domain]
            and set(parse_qs(parsed.query, keep_blank_values=True)) <= QUERY_KEYS
        )
    except (ValueError, TypeError):
        return False


# Only links inside navigation landmarks; never search results, forms or ads.
SNAPSHOT = r"""(() => {
 const blocked = /ad|sponsor|advert|login|signin|account|consent|download|广告|推广|登录|授权|下载/i;
 const links = [...document.querySelectorAll('nav a[href], [role="navigation"] a[href]')]
 .filter(a => !a.download && !a.closest('form,[role="dialog"],[data-ad],[data-text-ad]'))
 .filter(a => !blocked.test([a.textContent, a.getAttribute('aria-label'), a.id,
   a.className, a.parentElement?.className].join(' ')))
 .map(a => {const r=a.getBoundingClientRect();return {url:a.href,x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height};})
 .filter(a => a.w>0 && a.h>0 && a.x>0 && a.y>0 && a.x<innerWidth && a.y<innerHeight);
 return {url:location.href,width:innerWidth,height:innerHeight,links};
})()"""

EMPTY_POINT = r"""((x,y) => {
 const e=document.elementFromPoint(x,y);
 return !!e && (e===document.body || e===document.documentElement) &&
 !document.querySelector('dialog[open], [role="dialog"]');
})"""
