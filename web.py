"""Point d'entrée du dashboard web azaload.

Usage:
    python web.py                       # http://127.0.0.1:8000
    python web.py --host 0.0.0.0 --port 8080
    python web.py --reload              # dev: hot reload

Le scanner asynchrone démarre automatiquement avec le serveur (lifespan
hook FastAPI) et tourne en parallèle de l'API.
"""

from __future__ import annotations

import argparse


def main() -> None:
    p = argparse.ArgumentParser(description="azaload web dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="dev mode (auto-reload)")
    args = p.parse_args()

    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "uvicorn manquant. Installez les dépendances : pip install -r requirements.txt"
        )

    uvicorn.run(
        "webapp.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
