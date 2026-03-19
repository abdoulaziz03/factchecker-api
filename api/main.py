import os
import sys
import json
import re
import bcrypt
import hashlib
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv

try:
    from ddgs import DDGS
except:
    from duckduckgo_search import DDGS

try:
    from langdetect import detect
except:
    detect = lambda x: "fr"

try:
    from deep_translator import GoogleTranslator
except:
    GoogleTranslator = None

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
client_groq = Groq(api_key=GROQ_API_KEY)

app = FastAPI(title="FactChecker API", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TexteEntrant(BaseModel):
    texte: str
    utilisateur: str = "anonyme"


class Utilisateur(BaseModel):
    pseudo: str
    mot_de_passe: str


def get_mongo():
    from pymongo import MongoClient
    MONGO_URL = os.environ.get("MONGO_URL", "")
    return MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000, tlsInsecure=True)


@app.get("/")
def accueil():
    return {"message": "FactChecker API en ligne ✅"}


@app.post("/inscription")
def inscription(user: Utilisateur):
    try:
        client = get_mongo()
        db = client["factchecker"]
        if db["utilisateurs"].find_one({"pseudo": user.pseudo}):
            client.close()
            return {"succes": False, "message": "Ce pseudo est déjà pris"}
        mot_de_passe_hash = bcrypt.hashpw(
            user.mot_de_passe.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        db["utilisateurs"].insert_one({
            "pseudo":           user.pseudo,
            "mot_de_passe":     mot_de_passe_hash,
            "date_inscription": datetime.now().isoformat()
        })
        client.close()
        return {"succes": True, "message": f"Compte créé pour {user.pseudo} !"}
    except Exception as e:
        return {"succes": False, "message": str(e)}


@app.post("/connexion")
def connexion(user: Utilisateur):
    try:
        client = get_mongo()
        db = client["factchecker"]
        utilisateur = db["utilisateurs"].find_one({"pseudo": user.pseudo})
        client.close()
        if not utilisateur:
            return {"succes": False, "message": "Pseudo introuvable"}
        if bcrypt.checkpw(
            user.mot_de_passe.encode("utf-8"),
            utilisateur["mot_de_passe"].encode("utf-8")
        ):
            return {"succes": True, "message": f"Bienvenue {user.pseudo} !"}
        return {"succes": False, "message": "Mot de passe incorrect"}
    except Exception as e:
        return {"succes": False, "message": str(e)}


@app.get("/historique")
def get_historique(utilisateur: str = None):
    try:
        client = get_mongo()
        db = client["factchecker"]
        filtre = {"utilisateur": utilisateur} if utilisateur else {}
        historique = list(db["historique"].find(filtre, {"_id": 0}).sort("date", -1).limit(50))
        client.close()
        return historique
    except Exception as e:
        print(f"MongoDB : {e}")
        return []


def detecter_langue(texte):
    try:
        return detect(texte)
    except:
        return "fr"


def traduire_en_anglais(texte):
    try:
        if GoogleTranslator:
            return GoogleTranslator(source="auto", target="en").translate(texte)
    except:
        pass
    return texte


def generer_hash(texte):
    return hashlib.md5(texte.strip().lower().encode("utf-8")).hexdigest()


def chercher_cache(texte):
    try:
        client = get_mongo()
        db = client["factchecker"]
        hash_texte = generer_hash(texte)
        cache = db["cache"].find_one({"hash": hash_texte}, {"_id": 0})
        client.close()
        if cache:
            resultat = cache.get("resultat", {})
            if resultat and "couleur" in resultat and "verdict" in resultat:
                print(f"✅ Cache hit pour : {texte[:50]}")
                return resultat
    except Exception as e:
        print(f"Erreur cache : {e}")
    return None


def sauvegarder_cache(texte, resultat):
    try:
        client = get_mongo()
        db = client["factchecker"]
        hash_texte = generer_hash(texte)
        db["cache"].update_one(
            {"hash": hash_texte},
            {"$set": {
                "hash":     hash_texte,
                "texte":    texte,
                "resultat": resultat,
                "date":     datetime.now().isoformat()
            }},
            upsert=True
        )
        client.close()
    except Exception as e:
        print(f"Erreur sauvegarde cache : {e}")


def rechercher_sources(texte, nb=4):
    try:
        with DDGS() as ddgs:
            resultats = list(ddgs.text(texte, max_results=nb))
        return [{
            "titre":   r.get("title", ""),
            "url":     r.get("href", ""),
            "extrait": r.get("body", "")[:300],
            "type":    "web"
        } for r in resultats]
    except Exception as e:
        print(f"Erreur recherche web : {e}")
        return []


def rechercher_fact_checkers(texte_anglais):
    sources_fc = []
    sites = [
        "site:snopes.com",
        "site:factcheck.org",
        "site:afp.com factuel",
        "site:lemonde.fr decodeurs",
        "site:liberation.fr checknews"
    ]
    try:
        with DDGS() as ddgs:
            for site in sites[:3]:
                resultats = list(ddgs.text(f"{texte_anglais} {site}", max_results=1))
                for r in resultats:
                    sources_fc.append({
                        "titre":   r.get("title", ""),
                        "url":     r.get("href", ""),
                        "extrait": r.get("body", "")[:300],
                        "type":    "fact-checker"
                    })
    except Exception as e:
        print(f"Erreur fact-checkers : {e}")
    return sources_fc


def rechercher_wikipedia(texte_anglais):
    sources_wiki = []
    try:
        with DDGS() as ddgs:
            resultats = list(ddgs.text(f"{texte_anglais} site:wikipedia.org", max_results=2))
            for r in resultats:
                sources_wiki.append({
                    "titre":   r.get("title", ""),
                    "url":     r.get("href", ""),
                    "extrait": r.get("body", "")[:300],
                    "type":    "wikipedia"
                })
    except Exception as e:
        print(f"Erreur Wikipedia : {e}")
    return sources_wiki


def calculer_score_confiance(sources, verdict):
    score_base = {
        "Fiable": 0.75,
        "À vérifier": 0.50,
        "Probablement faux": 0.20
    }.get(verdict, 0.50)

    nb_sources = len(sources)
    if nb_sources >= 4:
        bonus_sources = 0.10
    elif nb_sources >= 2:
        bonus_sources = 0.05
    else:
        bonus_sources = 0.0

    fc_sites = ["snopes", "factcheck", "afp", "decodeurs", "checknews", "lemonde", "liberation", "wikipedia"]
    nb_fc = sum(1 for s in sources if any(fc in s.get("url", "").lower() for fc in fc_sites))
    bonus_fc = min(nb_fc * 0.05, 0.15)

    return round(min(score_base + bonus_sources + bonus_fc, 0.99), 2)


@app.post("/verifier")
def verifier_information(entree: TexteEntrant):
    try:
        cache = chercher_cache(entree.texte)
        if cache:
            cache["texte_original"] = entree.texte
            cache["depuis_cache"] = True
            return cache

        langue = detecter_langue(entree.texte)
        texte_anglais = traduire_en_anglais(entree.texte) if langue != "en" else entree.texte

        sources        = rechercher_sources(entree.texte, nb=4)
        sources_fc     = rechercher_fact_checkers(texte_anglais)
        sources_wiki   = rechercher_wikipedia(texte_anglais)
        toutes_sources = sources + sources_fc + sources_wiki

        contexte_sources = "\n".join(
            [f"- [{s.get('type','web')}] {s['titre']} : {s['extrait']}" for s in toutes_sources]
        ) if toutes_sources else "Aucune source trouvée."

        prompt = f"""Tu es un expert en fact-checking international rigoureux et objectif.
Analyse cette affirmation en tenant compte des sources trouvées sur le web.
Réponds UNIQUEMENT en JSON valide, sans texte avant ou après.

Affirmation : "{entree.texte}"
Langue détectée : {langue}

Sources trouvées (web + fact-checkers + Wikipedia) :
{contexte_sources}

Règles importantes :
- Pour les faits politiques (présidents, dirigeants, chefs d'état) : fie-toi aux sources web. Si elles confirment → "Fiable"
- Pour les théories du complot ou affirmations scientifiquement fausses → "Probablement faux"
- Si les sources sont contradictoires ou insuffisantes → "À vérifier"
- Ne dis jamais "Probablement faux" si les sources confirment l'affirmation
- Cite toujours une source précise dans ton explication

Réponds avec ce format JSON exact :
{{
  "verdict": "Fiable" ou "À vérifier" ou "Probablement faux",
  "score": 0.8,
  "couleur": "vert" ou "orange" ou "rouge",
  "explication": "Une phrase expliquant pourquoi en citant les sources",
  "langue": "{langue}"
}}"""

        reponse = client_groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=400
        )

        contenu  = reponse.choices[0].message.content
        match    = re.search(r'\{.*\}', contenu, re.DOTALL)
        resultat = json.loads(match.group())

        score_confiance = calculer_score_confiance(toutes_sources, resultat["verdict"])

        reponse_finale = {
            "texte_original":  entree.texte,
            "verdict":         resultat.get("verdict", "À vérifier"),
            "explication":     resultat.get("explication", ""),
            "score_fiabilite": score_confiance,
            "couleur":         resultat.get("couleur", "orange"),
            "langue":          langue,
            "sources":         sources,
            "sources_fc":      sources_fc,
            "sources_wiki":    sources_wiki,
            "nb_sources":      len(toutes_sources),
            "depuis_cache":    False
        }

        sauvegarder_cache(entree.texte, reponse_finale)

        try:
            client = get_mongo()
            db = client["factchecker"]
            db["historique"].insert_one({
                "texte":        entree.texte,
                "utilisateur":  entree.utilisateur,
                "verdict":      reponse_finale["verdict"],
                "explication":  reponse_finale["explication"],
                "score":        score_confiance,
                "couleur":      reponse_finale["couleur"],
                "langue":       langue,
                "sources":      toutes_sources,
                "nb_sources":   len(toutes_sources),
                "nb_fc":        len(sources_fc),
                "date":         datetime.now().isoformat()
            })
            client.close()
        except Exception as mongo_err:
            print(f"MongoDB : {mongo_err}")

        return reponse_finale

    except Exception as e:
        print(f"ERREUR : {e}")
        return {
            "texte_original":  entree.texte,
            "verdict":         "Erreur",
            "explication":     str(e),
            "score_fiabilite": 0.0,
            "couleur":         "orange",
            "langue":          "fr",
            "sources":         [],
            "sources_fc":      [],
            "sources_wiki":    [],
            "nb_sources":      0,
            "depuis_cache":    False
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)