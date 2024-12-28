import requests
from bs4 import BeautifulSoup
import os
import time
from datetime import datetime
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# -------------------------------------------------------------------------
# Author : XKC_yourgoth.com
# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# PARAMÈTRES GLOBAUX
# -------------------------------------------------------------------------
MIN_SIZE_BYTES = 1 * 1024 * 1024      # 1 Mo
MAX_SIZE_BYTES = 100 * 1024 * 1024    # 100 Mo
MAX_LINKS = 1000                     # Nombre maximum de liens à récupérer
MAX_PAGES = 20                       # Nombre maximum de pages à parcourir
THREADS = 20                         # Nombre de threads pour le téléchargement
SLEEP_BETWEEN_SEARCH = 10           # Pause (secondes) entre deux recherches
SEARCH_DELAY = 2                    # Pause (secondes) entre chaque page (anti-spam)
TIMEOUT = 10                        # Timeout (secondes) pour les requêtes réseau

# Durée maximale (en secondes) pour un cycle de recherche / téléchargement (20 minutes)
SESSION_DURATION = 20 * 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}

LOG_FILE = "erome_log.txt"  # Nom du fichier de log pour les mini-logs

# -------------------------------------------------------------------------
# FONCTIONS UTILITAIRES
# -------------------------------------------------------------------------
def get_current_time() -> str:
    """Retourne la date et l'heure courante au format YYYY-MM-DD HH:MM:SS."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_event(message: str, log_file: str = LOG_FILE) -> None:
    """
    Écrit un message horodaté dans le fichier de log spécifié.
    Exemple de log_file : 'erome_log.txt'.
    """
    timestamp = get_current_time()
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

def is_mp4_link(link_url: str) -> bool:
    """Vérifie si le lien se termine par .mp4 (contrôle simple)."""
    return link_url.lower().endswith(".mp4")

def clean_tag(tag_text: str) -> str:
    """
    Nettoie un tag en supprimant les caractères indésirables (#, espaces, etc.)
    et en remplaçant les espaces par des underscores.
    """
    return (
        tag_text.replace("#", "")
                .strip()
                .replace(" ", "_")
    )

# -------------------------------------------------------------------------
# FONCTIONS DE TEST DU PROXY
# -------------------------------------------------------------------------
def test_proxy(proxies: dict) -> bool:
    """
    Teste la validité du proxy en faisant une requête simple sur api.ipify.org.
    Retourne True si la requête aboutit (status_code=200), sinon False.
    """
    if not proxies:
        # Pas de proxy (None ou dict vide) -> Pas d'erreur à ce stade
        return True

    test_url = "https://api.ipify.org?format=json"
    try:
        r = requests.get(test_url, proxies=proxies, timeout=5)
        if r.status_code == 200:
            print("[test_proxy] Le proxy fonctionne. Réponse =", r.text)
            return True
        else:
            print(f"[test_proxy] Le proxy a retourné un code HTTP {r.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[test_proxy] Erreur lors du test du proxy : {e}")
        return False

def get_proxies() -> dict:
    """
    Demande à l'utilisateur s'il souhaite utiliser un proxy.
    Puis le type de proxy (HTTP/HTTPS ou SOCKS5).
    Gère éventuellement l'authentification (user, pass).
    Construit un dict 'proxies' compatible avec requests.
    
    Retourne un dict ou None si on ne veut pas de proxy.
    """
    use_proxy = input("Voulez-vous utiliser un proxy ? (o/n) : ").strip().lower()
    if use_proxy != 'o':
        print("[get_proxies] Pas de proxy.")
        return None

    # Choix du type de proxy
    print("Quel type de proxy souhaitez-vous utiliser ?")
    print("  1) HTTP/HTTPS")
    print("  2) SOCKS5")
    proxy_type_choice = input("Votre choix : ").strip()

    if proxy_type_choice not in ['1', '2']:
        print("Choix invalide. Pas de proxy utilisé.")
        return None

    # Demande IP/Port
    proxy_ip_port = input("Entrez l'IP et le port du proxy (ex: 27.79.244.82:16000) : ").strip()

    # Demande user, pass (facultatifs)
    user = input("Nom d'utilisateur (si besoin, sinon laisser vide) : ").strip()
    pwd = input("Mot de passe (si besoin, sinon laisser vide) : ").strip()

    # Construction de la chaîne
    if proxy_type_choice == '1':
        # HTTP/HTTPS
        if not proxy_ip_port.startswith("http"):
            proxy_ip_port = "http://" + proxy_ip_port

        if user and pwd:
            splitted = proxy_ip_port.split("://", maxsplit=1)
            scheme = splitted[0]
            host = splitted[1]
            final_proxy = f"{scheme}://{user}:{pwd}@{host}"
        else:
            final_proxy = proxy_ip_port

        proxies = {
            "http": final_proxy,
            "https": final_proxy
        }

    else:
        # SOCKS5
        if user and pwd:
            final_proxy = f"socks5://{user}:{pwd}@{proxy_ip_port}"
        else:
            final_proxy = f"socks5://{proxy_ip_port}"

        proxies = {
            "http": final_proxy,
            "https": final_proxy
        }

    print(f"[get_proxies] Test du proxy : {proxies}")
    if test_proxy(proxies):
        print("[get_proxies] Proxy validé.")
        return proxies
    else:
        print("[get_proxies] Le proxy ne fonctionne pas ou a échoué le test.")
        choice = input("Voulez-vous réessayer (r) ou continuer sans proxy (c) ? ").strip().lower()
        if choice == 'r':
            return get_proxies()  # On relance la fonction pour retenter
        else:
            print("[get_proxies] Continuer sans proxy.")
            return None

# -------------------------------------------------------------------------
# FONCTIONS POUR LA RECHERCHE DE LIENS
# -------------------------------------------------------------------------
def parse_page_for_links(html_content: str) -> list:
    """
    Analyse le HTML et renvoie la liste des liens qui contiennent '/a/' ou '/v/'.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    links_found = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/a/" in href or "/v/" in href:
            links_found.append(href)
    return links_found

def search_videos(tag: str, output_file: str, proxies: dict,
                  num_links: int = MAX_LINKS, 
                  max_pages: int = MAX_PAGES) -> list:
    """
    Recherche jusqu’à `num_links` liens contenant '/a/' ou '/v/' sur Erome,
    en paginant (jusqu'à `max_pages`) si nécessaire.
    Retourne une liste de liens uniques.
    """
    video_links = set()
    page = 1
    
    while len(video_links) < num_links and page <= max_pages:
        url = f"https://www.erome.com/search?q={tag}&page={page}"
        try:
            response = requests.get(url, headers=HEADERS, proxies=proxies, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"[{get_current_time()}] Erreur réseau: {e}")
            log_event(f"Erreur réseau lors de la recherche de vidéos : {e}")
            break

        if response.status_code != 200:
            print(f"[{get_current_time()}] Erreur HTTP {response.status_code} pour {url}. Arrêt pagination.")
            log_event(f"Erreur HTTP {response.status_code} pour {url} (recherche_videos).")
            break

        links_in_page = parse_page_for_links(response.text)
        found_on_page = 0
        
        for href in links_in_page:
            # Fabriquer l'URL absolue si nécessaire
            if not href.startswith("https://"):
                href = "https://www.erome.com" + href
            
            if href not in video_links:
                video_links.add(href)
                found_on_page += 1
            
            if len(video_links) >= num_links:
                break

        print(f"[{get_current_time()}] Page {page}: +{found_on_page} liens. (Total provisoire: {len(video_links)})")
        page += 1
        time.sleep(SEARCH_DELAY)  # éviter de surcharger le site

    # Sauvegarder les liens trouvés
    if video_links:
        with open(output_file, "a", encoding="utf-8") as f:
            for link in video_links:
                f.write(f"[{get_current_time()}] {link}\n")

        print(f"[{get_current_time()}] Total: {len(video_links)} liens pour le tag '{tag}', pages: {page-1}.")
    else:
        print(f"[{get_current_time()}] Aucun lien récupéré pour '{tag}'.")

    return list(video_links)

# -------------------------------------------------------------------------
# FONCTIONS POUR LE TÉLÉCHARGEMENT
# -------------------------------------------------------------------------
def parse_page_for_tags(html_content: str) -> list:
    """
    Analyse le HTML pour extraire les tags dans <p class="mt-10"> 
    (ex: <a> #Tag </a>).
    Retourne une liste de tags (sans le '#', espace -> underscore).
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    tags = []
    p_tags = soup.find("p", class_="mt-10")
    if p_tags:
        a_tags = p_tags.find_all("a", href=True)
        for a in a_tags:
            raw_text = a.get_text(strip=True)
            if raw_text:
                tags.append(clean_tag(raw_text))
    return tags

def get_video_src(html_content: str) -> str:
    """
    Analyse le HTML pour trouver la balise <video><source>,
    et renvoie l'URL (src) de la vidéo si trouvée, sinon None.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    video_tag = soup.find('video')
    if not video_tag:
        return None
    
    source_tag = video_tag.find('source')
    if not source_tag or not source_tag.get('src'):
        return None
    return source_tag['src']

def download_video(page_url: str,
                   save_folder: str,
                   in_progress: set,
                   downloaded_videos: set,
                   lock: Lock,
                   proxies: dict) -> None:
    """
    Télécharge la vidéo Erome pour une page (URL /a/ ou /v/),
    après vérification HEAD (taille, type).
    Renomme selon les 5 premiers tags trouvés.
    Inclut des logs pour détecter si un blocage a pu se produire
    (ex: statut 403, 429, etc.).
    """
    with lock:
        if page_url in downloaded_videos or page_url in in_progress:
            return
        in_progress.add(page_url)

    # Récupération de la page
    try:
        resp_page = requests.get(page_url, headers=HEADERS, proxies=proxies, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        log_event(f"Erreur GET sur {page_url} : {e}")
        print(f"[{get_current_time()}] Erreur GET sur {page_url} : {e}")
        with lock:
            in_progress.discard(page_url)
        return

    if resp_page.status_code != 200:
        # Exemple de blocage possible : 403, 429, etc.
        msg_block = f"Erreur GET (code={resp_page.status_code}) sur {page_url}"
        if resp_page.status_code == 403:
            msg_block = f"[BLOCK] Accès interdit (403) sur {page_url}"
        elif resp_page.status_code == 429:
            msg_block = f"[BLOCK] Trop de requêtes (429) sur {page_url}"

        log_event(msg_block)
        print(f"[{get_current_time()}] {msg_block}")
        
        with lock:
            in_progress.discard(page_url)
        return  # On arrête ce téléchargement, mais pas le script complet

    # Extraction des tags (max 5)
    tags_found = parse_page_for_tags(resp_page.text)[:5]
    tags_string = "_".join(tags_found)

    # Repérer la source MP4
    video_src = get_video_src(resp_page.text)
    if not video_src:
        log_event(f"Pas de source MP4 trouvée sur {page_url}")
        print(f"[{get_current_time()}] Pas de source MP4 trouvée sur {page_url}")
        with lock:
            in_progress.discard(page_url)
        return

    if not video_src.startswith("http"):
        video_src = "https:" + video_src

    if not is_mp4_link(video_src):
        log_event(f"Source non-MP4 sur {page_url} -> {video_src}")
        print(f"[{get_current_time()}] Source non-MP4 sur {page_url} -> {video_src}")
        with lock:
            in_progress.discard(page_url)
        return

    # HEAD : vérifier taille, type
    try:
        head_resp = requests.head(video_src, headers=HEADERS, proxies=proxies, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        log_event(f"Erreur HEAD sur {video_src} : {e}")
        print(f"[{get_current_time()}] Erreur HEAD sur {video_src} : {e}")
        with lock:
            in_progress.discard(page_url)
        return

    if head_resp.status_code != 200:
        msg_block = f"HEAD status {head_resp.status_code} sur {video_src}"
        if head_resp.status_code == 403:
            msg_block = f"[BLOCK] HEAD interdit (403) sur {video_src}"
        elif head_resp.status_code == 429:
            msg_block = f"[BLOCK] Trop de requêtes (429) sur {video_src}"

        log_event(msg_block)
        print(f"[{get_current_time()}] {msg_block}")
        
        with lock:
            in_progress.discard(page_url)
        return  # On arrête juste ce téléchargement

    ctype = head_resp.headers.get('Content-Type', '')
    clength_str = head_resp.headers.get('Content-Length', '0')
    try:
        clength = int(clength_str)
    except ValueError:
        clength = 0

    if not ctype.startswith('video'):
        log_event(f"HEAD indique un type non vidéo ({ctype}) sur {video_src}")
        print(f"[{get_current_time()}] Type non vidéo pour {video_src} ({ctype})")
        with lock:
            in_progress.discard(page_url)
        return

    if not (MIN_SIZE_BYTES <= clength <= MAX_SIZE_BYTES):
        log_event(f"HEAD indique une taille hors limites ({clength} bytes) sur {video_src}")
        print(f"[{get_current_time()}] Taille hors limites ({clength} bytes) pour {video_src}")
        with lock:
            in_progress.discard(page_url)
        return

    # Construire le nom de fichier
    original_name = video_src.split('/')[-1]
    final_name = f"{tags_string}_{original_name}" if tags_string else original_name
    save_path = os.path.join(save_folder, final_name)

    # Téléchargement
    try:
        video_resp = requests.get(video_src, stream=True, headers=HEADERS, proxies=proxies, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        log_event(f"Erreur GET (téléchargement) sur {video_src} : {e}")
        print(f"[{get_current_time()}] Erreur GET (téléchargement) sur {video_src} : {e}")
        with lock:
            in_progress.discard(page_url)
        return

    if video_resp.status_code != 200:
        msg_block = f"Erreur téléchargement (code={video_resp.status_code}) sur {video_src}"
        if video_resp.status_code == 403:
            msg_block = f"[BLOCK] Téléchargement interdit (403) sur {video_src}"
        elif video_resp.status_code == 429:
            msg_block = f"[BLOCK] Trop de requêtes (429) en téléchargement sur {video_src}"

        log_event(msg_block)
        print(f"[{get_current_time()}] {msg_block}")
        
        with lock:
            in_progress.discard(page_url)
        return

    tsize_str = video_resp.headers.get('content-length', '0')
    try:
        tsize = int(tsize_str)
    except ValueError:
        tsize = 0

    if tsize == 0:
        log_event(f"Pas de content-length ou 0 lors du téléchargement sur {video_src}")
        print(f"[{get_current_time()}] content-length=0 pour {video_src}")
        with lock:
            in_progress.discard(page_url)
        return

    print(f"[{get_current_time()}] Téléchargement : {final_name}")
    with tqdm(total=tsize, unit='B', unit_scale=True, desc=final_name) as pbar:
        downloaded_size = 0
        start_time = time.time()

        with open(save_path, 'wb') as f:
            for chunk in video_resp.iter_content(chunk_size=1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded_size += len(chunk)
                pbar.update(len(chunk))

                # Calcul de la vitesse
                elapsed = time.time() - start_time
                speed = downloaded_size / elapsed if elapsed > 0 else 0
                print(f"\r[{get_current_time()}] Vitesse : {speed/1024:.2f} KB/s", end='')

    # Vérification finale
    final_size = os.path.getsize(save_path)
    if final_size < 2000:
        # Fichier trop petit, on le supprime
        os.remove(save_path)
        log_event(f"Fichier trop petit après téléchargement (corrompu ?) : {final_name}")
        print(f"[{get_current_time()}] Fichier {final_name} trop petit (probablement corrompu). Supprimé.")
    else:
        print(f"\n[{get_current_time()}] Fichier enregistré : {final_name} ({final_size} octets)")
        with lock:
            downloaded_videos.add(page_url)

    with lock:
        in_progress.discard(page_url)

# -------------------------------------------------------------------------
# BOUCLE PRINCIPALE
# -------------------------------------------------------------------------
def main():
    """
    Boucle principale :
      1. Demande le tag et le proxy (HTTP/HTTPS ou SOCKS5).
      2. Recherche et télécharge pendant 20 minutes.
      3. Au bout de 20 minutes, on redemande à l'utilisateur
         s'il veut changer de tag ou arrêter.
      4. Recommence avec le nouveau tag si choisi.

    Les mini-logs (erome_log.txt) notent les blocages potentiels (403, 429)
    ou toute autre erreur notable, et on affiche aussi un message en console.
    """
    save_folder = "downloads"
    output_file = "video_links.txt"
    os.makedirs(save_folder, exist_ok=True)

    # Liste des vidéos déjà téléchargées
    downloaded_videos = set()
    if os.path.exists("downloaded_videos.txt"):
        with open("downloaded_videos.txt", 'r', encoding="utf-8") as f:
            for line in f:
                downloaded_videos.add(line.strip())

    lock = Lock()

    while True:
        tag = input("\nEntrez le tag à rechercher : ").strip()
        if not tag:
            print("[!] Tag vide, fin du programme.")
            break

        proxies = get_proxies()

        print(f"\n[{get_current_time()}] Début du cycle pour le tag : '{tag}' (20 minutes max).")
        start_cycle = time.time()

        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            while True:
                elapsed = time.time() - start_cycle
                if elapsed > SESSION_DURATION:
                    print(f"[{get_current_time()}] 20 minutes écoulées pour le tag '{tag}'.")
                    break

                in_progress = set()
                video_links = search_videos(
                    tag=tag, 
                    output_file=output_file,
                    proxies=proxies,
                    num_links=MAX_LINKS, 
                    max_pages=MAX_PAGES
                )
                if video_links:
                    futures = []
                    for link in video_links:
                        futures.append(executor.submit(
                            download_video,
                            link,
                            save_folder,
                            in_progress,
                            downloaded_videos,
                            lock,
                            proxies
                        ))
                    # Au lieu d'un simple fut.result(), on entoure d'un try/except
                    for fut in as_completed(futures):
                        try:
                            fut.result()
                        except Exception as e:
                            # On log l'exception et on continue
                            log_event(f"Exception non gérée dans un thread: {e}")
                            print(f"[{get_current_time()}] Exception non gérée: {e}")

                    # Mettre à jour la liste des téléchargées
                    with open("downloaded_videos.txt", 'w', encoding="utf-8") as f:
                        for url in downloaded_videos:
                            f.write(f"{url}\n")

                print(f"\n[{get_current_time()}] En pause {SLEEP_BETWEEN_SEARCH}s avant la prochaine recherche.")
                time.sleep(SLEEP_BETWEEN_SEARCH)
        
        choice = input(
            "\nLe cycle de 20 minutes est terminé. Voulez-vous :\n"
            "  [1] Rechercher un nouveau tag\n"
            "  [2] Quitter\n"
            "Votre choix : "
        ).strip()

        if choice == '1':
            continue
        else:
            print(f"[{get_current_time()}] Fin du programme.")
            break

if __name__ == "__main__":
    main()
