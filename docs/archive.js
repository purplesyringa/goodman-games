function $(template, ...args) {
	let html = template[0];
	for (let i = 0; i < args.length; i++) {
		if (args[i].unsafeHTML) {
			html += args[i].unsafeHTML;
		} else {
			html += (args[i] + "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)}`);
		}
		html += template[i + 1];
	}
	const node = document.createElement("div");
	node.innerHTML = html.trim();
	for (const link of node.querySelectorAll("a")) {
		if ((link.getAttribute("href") || "").startsWith("?")) {
			link.addEventListener("click", e => {
				let href = link.href;
				if (href.endsWith("?")) {
					href = href.slice(0, -1);
				}
				e.preventDefault();
				history.pushState(null, "", href);
				document.documentElement.scrollTop = 0;
				updatePage();
			});
		}
	}
	return node.childNodes[0];
}

async function caching(key, fn) {
	return await (caching.cache[key] || (caching.cache[key] = fn()));
}
caching.cache = {};

async function retrieveIndex() {
	return await caching("index", async () => await (await fetch("chunks/index.json")).json());
}

async function retrieveChunk(chunkId) {
	return await caching(
		chunkId,
		async () => {
			const gzipped = (await fetch(`chunks/${chunkId}.json.gz`)).body;
			const reader = gzipped.pipeThrough(new DecompressionStream("gzip")).getReader();
			const decoder = new TextDecoder();
			const parts = [];
			while (true) {
				let {done, value} = await reader.read();
				parts.push(decoder.decode(value));
				if (done) {
					break;
				}
			}
			return JSON.parse(parts.join(""));
		}
	);
}

async function loadKey(key) {
	const index = await retrieveIndex();
	return (await retrieveChunk(index[key]))[key];
}

async function updatePage() {
	const mainNode = document.querySelector("main");
	mainNode.innerHTML = "";

	const key = location.search ? location.search.slice(1).split("/")[0] : "root";
	await renderKey(key, true);
}

function formatDateTime(datetime) {
	const date = new Date(datetime);
	return date.toLocaleDateString("en-US") + ", " + date.toLocaleTimeString("en-US");
}

function toSlug(text) {
	return text.replace(/[^a-zA-Z0-9_]/g, "-").replace(/-+/g, "-").replace(/^-|-$/, "");
}

async function renderKey(key, topLevel) {
	const mainNode = document.querySelector("main");
	const data = await loadKey(key);

	mainNode.classList.toggle("kind-forum", data.kind === "forum");
	mainNode.classList.toggle("kind-topic", data.kind === "topic");

	if (data.kind === "forum") {
		if (topLevel) {
			document.title = data.title;
			if (key === "root") {
				mainNode.appendChild($`<h1>${data.title}</h1>`);
			} else {
				mainNode.appendChild($`<h1><a class="back" href="?"><i class="fa-solid fa-chevron-left"></i></a>${data.title}</h1>`);
			}
		}

		for (const row of data.items) {
			if (row.kind === "forum") {
				if (row.target_key === "f82") {
					// A redirect that failed to parse
					continue;
				}
				mainNode.appendChild($`
					<div class="item">
						<div class="icon">
							<i class="fa-solid fa-fw fa-list"></i>
						</div>
						<div class="info">
							<h2><a href="?${row.target_key}/${toSlug(row.title)}">${row.title}</a></h2>
							<div class="description">${row.description}</div>
						</div>
					</div>
				`);
			} else if (row.kind === "topic") {
				mainNode.appendChild($`
					<div class="item">
						<div class="icon">
							<i class="fa-solid fa-fw fa-comments"></i>
						</div>
						<div class="info">
							<h2><a href="?${row.target_key}/${toSlug(row.title)}">${row.title}</a></h2>
							<div class="description">by ${row.user_name}, on ${formatDateTime(row.datetime)}</div>
						</div>
					</div>
				`);
			} else if (row.kind === "redirect") {
				mainNode.appendChild($`
					<div class="item">
						<div class="icon">
							<i class="fa-solid fa-fw fa-location-arrow"></i>
						</div>
						<div class="info">
							<h2><a href="${row.target_url}">${row.title}</a></h2>
							<div class="description">${row.description}</div>
						</div>
					</div>
				`);
			} else if (row.kind === "inline-forum") {
				mainNode.appendChild($`<div class="inline-forum">${row.title}</div>`);
				await renderKey(row.target_key, false);
			}
		}
	} else if (data.kind === "topic") {
		if (topLevel) {
			document.title = data.items[0].title;
			mainNode.appendChild($`<h1><a class="back" href="?${key.replace(/t.*/, "")}"><i class="fa-solid fa-chevron-left"></i></a>${data.items[0].title}</h1>`);
		}

		for (const row of data.items) {
			const node = $`
				<div class="post" id="post${row.post_id}">
					<div class="top">
						<div class="info">
							<h2>${row.title}</h2>
							<div class="description">by ${row.user_name}, on ${formatDateTime(row.datetime)}</div>
						</div>
						<div class="hashtag">
							<a href="#post${row.post_id}"><i class="fa-solid fa-hashtag"></i></a>
						</div>
					</div>
					<div class="body">
						${{unsafeHTML: row.content}}
					</div>
				</div>
			`;
			for (const hiddenNode of node.querySelectorAll("cite .responsive-hide")) {
				hiddenNode.remove();
			}
			for (const link of node.querySelectorAll("cite a")) {
				if (link.hasAttribute("data-post-id")) {
					link.remove();
				} else {
					link.replaceWith(link.childNodes[0]);
				}
			}
			mainNode.appendChild(node);
		}
	}
}

updatePage();
window.addEventListener("popstate", updatePage);
