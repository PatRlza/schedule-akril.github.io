#!/usr/bin/env python3
"""
Синхронизация расписаний с публичной папки Яндекс.Диска в этот репозиторий.

Как это работает:
  1. Спрашиваем у Яндекс.Диска список файлов в публичной папке (без токена —
     публичные ресурсы можно читать анонимно).
  2. Для каждого .xlsx/.xls файла получаем прямую ссылку на скачивание и
     сохраняем файл в корень репозитория под тем же именем.
  3. Если содержимое файла не изменилось (совпадает хэш) — просто пропускаем,
     чтобы не создавать пустые коммиты.
  4. Если что-то изменилось — печатаем "changed=true" в GITHUB_OUTPUT, и
     workflow сам сделает commit + push.

Меняется на ходу может только PUBLIC_KEY (если ссылку на папку когда-нибудь
пересоздадут) и, возможно, TARGET_DIR, если сайт будет ждать файлы не в
корне репозитория.
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PUBLIC_KEY = "https://disk.yandex.ru/d/JuK8aJ2gV8XCjA"
META_URL = "https://cloud-api.yandex.net/v1/disk/public/resources"
DOWNLOAD_URL = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
TARGET_DIR = "."  # repo root — matches what the site's fetch code expects
ALLOWED_EXT = (".xlsx", ".xls")


def api_get(url, params):
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_bytes(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def list_public_items():
    """Returns a flat list of file entries (dicts with at least name/path),
    recursing one level into subfolders if the public link is itself a folder
    that contains subfolders (harmless no-op if it's already flat)."""
    data = api_get(META_URL, {"public_key": PUBLIC_KEY, "limit": 200})

    if data.get("type") == "file":
        return [data]

    items = data.get("_embedded", {}).get("items", [])
    flat = []
    for item in items:
        if item.get("type") == "dir":
            try:
                sub = api_get(META_URL, {
                    "public_key": PUBLIC_KEY,
                    "path": item.get("path", ""),
                    "limit": 200,
                })
                flat.extend(sub.get("_embedded", {}).get("items", []))
            except urllib.error.HTTPError as e:
                print(f"  (пропускаю подпапку {item.get('name')}: {e})")
        else:
            flat.append(item)
    return flat


def sha256_of(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    try:
        items = list_public_items()
    except urllib.error.HTTPError as e:
        print(f"Не удалось получить список файлов с Яндекс.Диска: {e}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Сетевая ошибка при обращении к Яндекс.Диску: {e}")
        sys.exit(1)

    changed = False

    for item in items:
        name = item.get("name") or ""
        if not name.lower().endswith(ALLOWED_EXT):
            continue

        path = item.get("path", "")
        try:
            href_data = api_get(DOWNLOAD_URL, {"public_key": PUBLIC_KEY, "path": path})
            content = fetch_bytes(href_data["href"])
        except Exception as e:
            print(f"  Не удалось скачать {name}: {e}")
            continue

        local_path = os.path.join(TARGET_DIR, name)
        new_hash = hashlib.sha256(content).hexdigest()
        old_hash = sha256_of(local_path)

        if new_hash == old_hash:
            print(f"  Без изменений: {name}")
            continue

        with open(local_path, "wb") as f:
            f.write(content)
        print(f"  Обновлено: {name}")
        changed = True

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    if not changed:
        print("Новых файлов и изменений не найдено.")


if __name__ == "__main__":
    main()
