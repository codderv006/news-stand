import os, re, sqlite3, hashlib, html, json, asyncio, threading
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from urllib.parse import quote_plus
import feedparser
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "newsstand.db")
SOURCES = os.path.join(BASE, "sources.json")
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "30"))

def now():
    return datetime.now(timezone.utc).isoformat()

def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS articles(
      id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT UNIQUE NOT NULL,
      source TEXT NOT NULL, language TEXT DEFAULT 'en', region TEXT DEFAULT 'India',
      state TEXT, city TEXT, category TEXT DEFAULT 'general', importance REAL DEFAULT 5,
      published_at TEXT, summary TEXT, fetched_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_articles_published ON articles(published_at);
    CREATE INDEX IF NOT EXISTS ix_articles_region ON articles(region);
    CREATE INDEX IF NOT EXISTS ix_articles_state ON articles(state);
    CREATE INDEX IF NOT EXISTS ix_articles_category ON articles(category);
    CREATE TABLE IF NOT EXISTS epapers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, newspaper TEXT NOT NULL,
      language TEXT, region TEXT, state TEXT, city TEXT, edition TEXT,
      official_url TEXT NOT NULL, archive_url TEXT, notes TEXT,
      UNIQUE(newspaper, edition, official_url)
    );
    CREATE TABLE IF NOT EXISTS refresh_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
      source TEXT, fetched INTEGER DEFAULT 0, ok INTEGER DEFAULT 1, error TEXT
    );
    """)
    c.commit(); c.close()

def load_config():
    with open(SOURCES, encoding="utf-8") as f:
        return json.load(f)

def clean(s):
    s = re.sub(r"<[^>]*>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()

def category(title, desc=""):
    t=(title+" "+desc).lower()
    rules=[
      ("politics", ["election","minister","government","parliament","congress","bjp","president","prime minister","chief minister","supreme court","court","cabinet"]),
      ("business", ["market","stock","shares","economy","inflation","bank","rupee","company","business","gdp","trade","ipo","rbi"]),
      ("technology", ["artificial intelligence","ai ","technology","tech","software","chip","iphone","google","microsoft","cyber","robot"]),
      ("sports", ["cricket","football","fifa","tennis","olympic","sports","match","wicket","goal","league"]),
      ("science", ["space","nasa","science","research","climate","isro","astronomy","earthquake"]),
      ("health", ["health","hospital","disease","doctor","medical","virus","vaccine","outbreak"]),
      ("entertainment", ["movie","film","actor","actress","music","bollywood","celebrity","ott"]),
      ("weather", ["rain","rainfall","storm","cyclone","weather","flood","heatwave","temperature"]),
    ]
    for k, words in rules:
        if any(w in t for w in words): return k
    return "general"

def importance(title, desc, source_priority=5):
    t=(title+" "+desc).lower()
    score=float(source_priority)
    boosts={
      "breaking":2,"latest":1,"war":2,"earthquake":2,"cyclone":2,"flood":1.5,
      "election":1.5,"supreme court":1,"prime minister":1,"market":.5
    }
    for w,b in boosts.items():
        if w in t: score += b
    return min(10, max(1, round(score,1)))

def published(e):
    try:
        if getattr(e,"published_parsed",None):
            return datetime(*e.published_parsed[:6],tzinfo=timezone.utc).isoformat()
        if getattr(e,"updated_parsed",None):
            return datetime(*e.updated_parsed[:6],tzinfo=timezone.utc).isoformat()
    except Exception: pass
    return now()

def summary(title, desc):
    desc=clean(desc)
    if not desc: return title
    parts=re.split(r"(?<=[.!?])\s+",desc)
    out=" ".join(parts[:2]).strip()
    return out[:277]+"..." if len(out)>280 else out

def insert_article(src,e):
    title=clean(getattr(e,"title",""))
    url=getattr(e,"link","")
    if not title or not url: return False
    desc=clean(getattr(e,"summary","") or getattr(e,"description",""))
    aid=hashlib.sha256(url.encode()).hexdigest()[:32]
    c=db()
    c.execute("""INSERT INTO articles
      (id,title,url,source,language,region,state,city,category,importance,published_at,summary,fetched_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(url) DO UPDATE SET
       title=excluded.title, summary=excluded.summary, published_at=excluded.published_at,
       category=excluded.category, importance=excluded.importance, fetched_at=excluded.fetched_at""",
      (aid,title,url,src["name"],src.get("language","en"),src.get("region","India"),
       src.get("state"),src.get("city"),category(title,desc),
       importance(title,desc,src.get("priority",5)),published(e),summary(title,desc),now()))
    c.commit(); c.close()
    return True

def fetch_source(src):
    started=now()
    try:
        feed=feedparser.parse(src["url"])
        n=0
        for e in feed.entries[:src.get("limit",50)]:
            if insert_article(src,e): n+=1
        c=db(); c.execute("INSERT INTO refresh_log(started_at,finished_at,source,fetched,ok) VALUES(?,?,?,?,1)",
                           (started,now(),src["name"],n)); c.commit(); c.close()
        return {"source":src["name"],"count":n,"ok":True}
    except Exception as ex:
        c=db(); c.execute("INSERT INTO refresh_log(started_at,finished_at,source,fetched,ok,error) VALUES(?,?,?,?,0,?)",
                           (started,now(),src["name"],0,str(ex))); c.commit(); c.close()
        return {"source":src["name"],"count":0,"ok":False,"error":str(ex)}

def seed_epapers():
    c=db()
    for src in load_config()["sources"]:
        for p in src.get("epapers",[]):
            c.execute("""INSERT OR IGNORE INTO epapers
              (newspaper,language,region,state,city,edition,official_url,archive_url,notes)
              VALUES(?,?,?,?,?,?,?,?,?)""",
              (p["name"],p.get("language",src.get("language","en")),p.get("region",src.get("region")),
               p.get("state",src.get("state")),p.get("city",src.get("city")),p.get("edition",""),
               p["official_url"],p.get("archive_url"),p.get("notes","")))
    c.commit(); c.close()

def refresh_all():
    results=[fetch_source(s) for s in load_config()["sources"] if s.get("enabled",True)]
    seed_epapers()
    return results

def articles_query(region=None,state=None,city=None,cat=None,source=None,q=None,date=None,limit=120):
    where=[]; args=[]
    for col,val in [("region",region),("state",state),("city",city),("category",cat),("source",source)]:
        if val: where.append(col+"=?"); args.append(val)
    if q:
        where.append("(title LIKE ? OR summary LIKE ?)")
        args += [f"%{q}%",f"%{q}%"]
    if date:
        where.append("date(published_at)=date(?)"); args.append(date)
    sql="SELECT * FROM articles"
    if where: sql+=" WHERE "+" AND ".join(where)
    sql+=" ORDER BY importance DESC, published_at DESC LIMIT ?"
    args.append(min(max(int(limit),1),500))
    c=db(); rows=[dict(r) for r in c.execute(sql,args).fetchall()]; c.close()
    return rows

def articles_with_date_fallback(region=None,state=None,city=None,cat=None,source=None,q=None,date=None,limit=120):
    rows=articles_query(region,state,city,cat,source,q,date,limit)
    if date and not rows:
        return articles_query(region,state,city,cat,source,q,None,limit),False
    return rows,True

def cluster_key(title):
    words=re.findall(r"[a-z0-9]{4,}", title.lower())
    stop={"with","from","that","this","after","over","into","will","says","said","have","been","their","india","world"}
    return " ".join(sorted(set(w for w in words if w not in stop))[:8])

def clustered(rows):
    groups={}
    for a in rows:
        k=cluster_key(a["title"])
        groups.setdefault(k,[]).append(a)
    out=[]
    for vals in groups.values():
        top=max(vals,key=lambda x:(x["importance"],x["published_at"] or ""))
        top=dict(top); top["source_count"]=len({x["source"] for x in vals})
        top["sources"]=sorted({x["source"] for x in vals})
        top["related"]=vals[:6]
        out.append(top)
    return sorted(out,key=lambda x:(x["importance"],x["source_count"],x["published_at"] or ""),reverse=True)

def background_loop(stop):
    while not stop.wait(REFRESH_MINUTES*60):
        try: refresh_all()
        except Exception: pass

stop_event=threading.Event()

@asynccontextmanager
async def lifespan(app):
    init_db(); seed_epapers()
    # Initial refresh is intentionally in a thread so startup stays responsive.
    threading.Thread(target=refresh_all,daemon=True).start()
    threading.Thread(target=background_loop,args=(stop_event,),daemon=True).start()
    yield
    stop_event.set()

app=FastAPI(title="Newsstand",lifespan=lifespan)
STATIC_DIR=os.path.join(BASE,"static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")

@app.get("/",response_class=HTMLResponse)
def home():
    return open(os.path.join(BASE,"index.html"),encoding="utf-8").read()

@app.get("/api/articles")
def api_articles(region=None,state=None,city=None,category=None,source=None,q=None,date=None,limit=120,cluster=False):
    rows,date_match=articles_with_date_fallback(region,state,city,category,source,q,date,limit)
    return {"articles":clustered(rows) if str(cluster).lower()=="true" else rows,"requested_date":date,"date_match":date_match}

@app.get("/api/briefing")
def briefing(date=None,region=None,state=None,city=None,q=None):
    rows,date_match=articles_with_date_fallback(region,state,city,q=q,date=date,limit=300)
    return {"date":date or datetime.now().date().isoformat(),"stories":clustered(rows)[:25],"date_match":date_match}

@app.get("/api/epapers")
def api_epapers(region=None,state=None,city=None,language=None,q=None,date=None):
    where=[]; args=[]
    for col,val in [("region",region),("state",state),("city",city),("language",language)]:
        if val: where.append(col+"=?"); args.append(val)
    if q:
        where.append("(newspaper LIKE ? OR edition LIKE ?)"); args += [f"%{q}%",f"%{q}%"]
    sql="SELECT * FROM epapers"
    if where: sql+=" WHERE "+" AND ".join(where)
    sql+=" ORDER BY region,state,city,newspaper,edition"
    c=db(); rows=[dict(r) for r in c.execute(sql,args).fetchall()]; c.close()
    for r in rows:
        r["requested_date"]=date
        r["access_type"]="official_link"
    return {"epapers":rows}

@app.get("/api/meta")
def meta(region=None,state=None,city=None):
    c=db()
    where=[]; args=[]
    for col,val in [("region",region),("state",state),("city",city)]:
        if val: where.append(col+"=?"); args.append(val)
    clause=" WHERE "+" AND ".join(where) if where else ""
    def q(sql): return [dict(x) for x in c.execute(sql.replace("__WHERE__",clause),args).fetchall()]
    out={
            "regions":q("SELECT region,COUNT(*) n FROM articles__WHERE__ GROUP BY region ORDER BY n DESC"),
            "states":q("SELECT state,COUNT(*) n FROM articles__WHERE__ AND state IS NOT NULL GROUP BY state ORDER BY n DESC" if clause else "SELECT state,COUNT(*) n FROM articles WHERE state IS NOT NULL GROUP BY state ORDER BY n DESC"),
            "cities":q("SELECT city,COUNT(*) n FROM articles__WHERE__ AND city IS NOT NULL GROUP BY city ORDER BY n DESC" if clause else "SELECT city,COUNT(*) n FROM articles WHERE city IS NOT NULL GROUP BY city ORDER BY n DESC"),
            "categories":q("SELECT category,COUNT(*) n FROM articles__WHERE__ GROUP BY category ORDER BY n DESC"),
            "sources":q("SELECT source,COUNT(*) n FROM articles__WHERE__ GROUP BY source ORDER BY n DESC")
    }
    c.close(); return out

@app.get("/api/locations")
def locations():
    cfg=load_config()
    states=sorted({s.get("state") for s in cfg["sources"] if s.get("state")})
    cities=sorted({s.get("city") for s in cfg["sources"] if s.get("city")})
    return {"states":states,"cities":cities}

@app.post("/api/refresh")
def api_refresh():
    return {"results":refresh_all(),"finished_at":now()}

@app.get("/api/status")
def status():
    c=db()
    count=c.execute("SELECT COUNT(*) n FROM articles").fetchone()["n"]
    papers=c.execute("SELECT COUNT(*) n FROM epapers").fetchone()["n"]
    last=c.execute("SELECT MAX(finished_at) x FROM refresh_log").fetchone()["x"]
    c.close()
    return {"articles":count,"epapers":papers,"last_refresh":last,"refresh_minutes":REFRESH_MINUTES}

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")),reload=True)
