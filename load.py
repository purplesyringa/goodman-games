import aiohttp
import asyncio
from dataclasses import dataclass
import html
import json
from sqlitedict import SqliteDict


BASE = "https://goodman-games.com/forums/"
PARALLELISM = 16

visited = set()
db = SqliteDict("Goodman.sqlite", encode=json.dumps, decode=json.loads, autocommit=True)
sem = asyncio.Semaphore(PARALLELISM)


def save(key: str, value):
    db[key] = value


@dataclass
class Redirect:
    target_url: str


async def get_page(session: aiohttp.ClientSession, url: str) -> str | Redirect:
    async with sem:
        try:
            resp = await session.get(url)
            if resp.history:
                return Redirect(str(resp.history[1].url))
            return await resp.text()
        except Exception:
            print(url)
            raise


async def scan_forum(session: aiohttp.ClientSession, text: str, key: str):
    if key in visited or key in db:
        return
    visited.add(key)

    print("Scanning", key)

    forum_title = None
    items = []
    tasks = []

    while True:
        if '<h2 class="forum-title">' in text:
            forum_title = html.unescape(text.split('<h2 class="forum-title">')[1].split('>')[1].split('<')[0])
        else:
            forum_title = html.unescape(text.split('<h1>')[1].split('</h1>')[0])

        for item_up in text.split('<ul class="topiclist">')[1:]:
            header_group = item_up.split('<div class="list-inner">')[1].split('</div>')[0]
            if '<a' in header_group:
                title = html.unescape(header_group.split('>')[1].split('<')[0])
                target_url = html.unescape(header_group.split('<a href="')[1].split('"')[0])
                forum_id = target_url.split('f=')[1].split('&')[0]
                target_key = f"f{forum_id}"
                items.append({
                    "kind": "inline-forum",
                    "title": title,
                    "target_key": target_key,
                })
                target_text = await get_page(session, BASE + target_url)
                assert not isinstance(target_text, Redirect)
                tasks.append(asyncio.create_task(scan_forum(session, target_text, target_key)))
                continue

            title = html.unescape(header_group)
            if title == "Active topics":
                continue
            items.append({
                "kind": "group",
                "title": title,
            })

            for item in item_up.split('<li class="row')[1:]:
                after_title = item.split('<a href="')[1]
                target_url = html.unescape(after_title.split('"')[0])
                title = html.unescape(after_title.split('>')[1].split('<')[0])
                description_html = item.split('<br />')[1].strip()
                if description_html.startswith('<div class="responsive-show') or description_html.startswith("<strong>Moderators:</strong>"):
                    description = ""
                else:
                    description = html.unescape(description_html)

                if target_url.startswith("./viewforum.php"):
                    forum_id = target_url.split('f=')[1].split('&')[0]
                    target_key = f"f{forum_id}"
                    target_text = await get_page(session, BASE + target_url)
                    if isinstance(target_text, Redirect):
                        items.append({
                            "kind": "redirect",
                            "title": title,
                            "description": description,
                            "target_url": target_text.target_url,
                        })
                    else:
                        items.append({
                            "kind": "forum",
                            "title": title,
                            "description": description,
                            "target_key": target_key,
                        })
                        tasks.append(asyncio.create_task(scan_forum(session, target_text, target_key)))
                elif target_url.startswith("./viewtopic.php"):
                    forum_id = target_url.split('f=')[1].split('&')[0]
                    topic_id = target_url.split('t=')[1].split('&')[0]
                    user_info = item.split('<div class="topic-poster')[1].split('</div>')[0]
                    if '<a href="./' in user_info:
                        user_id = int(user_info.split('./memberlist.php?mode=viewprofile&amp;u=')[1].split('"')[0].split('&')[0])
                    else:
                        user_id = -1
                    user_name = html.unescape(user_info.split('class="username')[1].split('>')[1].split('<')[0])
                    datetime = user_info.split('datetime="')[1].split('"')[0]
                    target_key = f"f{forum_id}t{topic_id}"
                    items.append({
                        "kind": "topic",
                        "title": title,
                        "target_key": target_key,
                        "user_id": user_id,
                        "user_name": user_name,
                        "datetime": datetime,
                    })
                    tasks.append(asyncio.create_task(scan_topic(session, BASE + target_url, target_key)))
                elif target_url.startswith("https://"):
                    items.append({
                        "kind": "redirect",
                        "title": title,
                        "description": description,
                        "target_url": target_url,
                    })
                else:
                    print("Unknown URL", target_url)
                    raise SystemExit(1)

        if '<li class="arrow next">' in text:
            url = BASE + html.unescape(text.split('<li class="arrow next">')[1].split('href="')[1].split('"')[0])
            text = await get_page(session, url)
            assert not isinstance(text, Redirect)
        else:
            break

    await asyncio.gather(*tasks)

    save(key, {"kind": "forum", "title": forum_title, "items": items})


async def scan_topic(session: aiohttp.ClientSession, url: str, key: str):
    if key in visited or key in db:
        return
    visited.add(key)

    items = []

    while True:
        text = await get_page(session, url)
        assert not isinstance(text, Redirect)

        for item in text.split('class="post ')[1:]:
            title = html.unescape(item.split('<h3')[1].split('>')[2].split('</a')[0])
            user_info = item.split('<p class="author">')[1].split('</p>')[0]
            if '<a href="./' in user_info:
                user_id = int(user_info.split('./memberlist.php?mode=viewprofile&amp;u=')[1].split('"')[0].split('&')[0])
            else:
                user_id = -1
            user_name = html.unescape(user_info.split('class="username')[1].split('>')[1].split('<')[0])
            datetime = user_info.split('datetime="')[1].split('"')[0]
            after_post_content = item.split('<div id="post_content')[1]
            post_id = int(after_post_content.split('"')[0])
            after_content = item.partition('<div class="content">')[2]

            i = 0
            content = ""
            div_nesting = 0
            while True:
                assert i + 1 < len(after_content)
                if after_content[i] == "<":
                    tag_end = after_content.index(">", i) + 1
                    tag = after_content[i + 1:tag_end - 1].split()[0]
                    if tag == "div":
                        div_nesting += 1
                    elif tag == "/div":
                        if div_nesting == 0:
                            break
                        div_nesting -= 1
                    content += after_content[i:tag_end]
                    i = tag_end
                else:
                    tag_start = after_content.find("<", i)
                    if tag_start == -1:
                        tag_start = len(after_content)
                    content += after_content[i:tag_start]
                    i = tag_start

            items.append({
                "title": title,
                "user_id": user_id,
                "user_name": user_name,
                "datetime": datetime,
                "post_id": post_id,
                "content": content,
            })

        if '<li class="arrow next">' in text:
            url = BASE + html.unescape(text.split('<li class="arrow next">')[1].split('href="')[1].split('"')[0])
        else:
            break

    save(key, {"kind": "topic", "items": items})


async def main():
    async with aiohttp.ClientSession() as session:
        text = await get_page(session, BASE)
        assert not isinstance(text, Redirect)
        await scan_forum(session, text, "root")


asyncio.run(main())
