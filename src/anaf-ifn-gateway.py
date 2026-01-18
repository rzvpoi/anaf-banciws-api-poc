"""
ANAF BANCIWS Gateway (Proof of Concept)

Author: Tudor Poienariu
Created: 2026-01-16
Last updated: 2026-01-16

Description:
    Proof of concept gateway for integrating with ANAF BANCIWS REST services
    protected by F5 Big-IP APM. The gateway demonstrates how to establish
    a browser-style session using mTLS and reuse it for subsequent API calls.

Important notes:
    - This implementation is a POC and NOT intended for production use.
    - It relies on the current behavior of F5 Big-IP access policies.
    - Changes in ANAF or F5 configuration may break this approach.
    - All XML payloads follow ANAF official documentation and XSDs.

References:
    https://static.anaf.ro/static/IFN/instructiuni_ifn.html
"""

import logging
import requests
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from typing import Optional
import base64

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ANAF-IFN-Gateway")

CERT_PATH = "./certs/client.pem"
KEY_PATH = "./certs/client.key"

API_BASE_URL = "https://financiart.anaf.ro/BANCIWS/rest/"

# anaf uses certs issued by digicert so there shouldn't be any issues here
# anaf only uses the client.cert with its internal CA to verify authenticity
# in case of the system not trusing the Digicert CA you can add the CA chain here
VERIFY_CA = True

HEADERS = {
    "Content-Type": "application/xml",
    "User-Agent": "anaf-api-integration/v1.0",
}


class ListaMesajeRequest(BaseModel):
    zile: str = "1/24"


class StareMesajRequest(BaseModel):
    index_incarcare: str


class DescarcareMesajRequest(BaseModel):
    id_portal: str


class UploadMesajRequest(BaseModel):
    fisier_b64: str


# --- ANAF Gateway Logic ---
class ANAFGateway:
    def __init__(self):
        self.session = requests.Session()
        self.session.cert = (CERT_PATH, KEY_PATH)
        self.session.verify = VERIFY_CA
        self.session.headers.update(HEADERS)
        self._authenticated = False

    # IMPORTANT:
    # This request is intentionally used only to trigger the F5 Big-IP
    # authentication flow and establish a session (cookies).
    # The response payload itself is irrelevant.
    def _authenticate(self):
        logger.info("Gateway: establishing fresh F5 session...")
        url = API_BASE_URL + "listaMesaje"

        payload = """<?xml version="1.0" encoding="UTF-8"?>
        <header xmlns="mfp:anaf:dgti:banci:reqListaMesaje:v1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <listaMesaje Zile="1/24"/>
        </header>"""

        try:
            # allow_redirects=True is key for F5 to set cookies during redirects
            response = self.session.post(
                url, data=payload, timeout=30, allow_redirects=True
            )

            if response.status_code not in [200, 405]:
                logger.error(f"Auth failed with status {response.status_code}")
                raise HTTPException(status_code=502, detail="Upstream ANAF Auth Failed")

            # Check if we got the HTML login page instead of XML (mtls failed with f5)
            if (
                "text/html" in response.headers.get("Content-Type", "")
                or "<html" in response.text[:100].lower()
            ):
                logger.error(
                    "Auth failed: Received HTML login page instead of API response."
                )
                raise HTTPException(
                    status_code=502, detail="ANAF Gateway blocked by F5 (HTML response)"
                )

            logger.info("Gateway: F5 Session established successfully.")
            self._authenticated = True

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during auth: {e}")
            raise HTTPException(status_code=503, detail="ANAF Connection Error")

    def post_xml(self, endpoint: str, payload: str):
        url = API_BASE_URL + endpoint

        if not self._authenticated:
            self._authenticate()

        logger.debug(f"Sending request to {endpoint}")

        try:
            # IMPORTANT: when doing requests to the API disable redirects so if the session
            # timed out it would not go to the auth procces from here.
            response = self.session.post(
                url, data=payload, timeout=60, allow_redirects=False
            )

            # If F5 returns HTML, redirects, or auth-related status codes,
            # assume the session expired and re-authenticate once.
            session_expired = (
                response.status_code in [401, 403, 405, 302, 301]
                or "text/html" in response.headers.get("Content-Type", "")
                or "<html" in response.text[:100].lower()
            )

            if session_expired:
                logger.warning(
                    "F5 Session likely expired. Re-authenticating and retrying..."
                )
                self._authenticate()
                response = self.session.post(
                    url, data=payload, timeout=60, allow_redirects=False
                )

            return response

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise HTTPException(status_code=502, detail=f"Upstream Error: {str(e)}")


gateway = ANAFGateway()
app = FastAPI(title="ANAF IFN Gateway")


# Endpoints
@app.get(
    "/health",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def health_check():
    return Response(media_type="application/xml", status_code=200)


@app.post(
    "/lista-mesaje",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def get_lista_mesaje(req: ListaMesajeRequest):
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
        <header xmlns="mfp:anaf:dgti:banci:reqListaMesaje:v1"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <listaMesaje Zile="{req.zile}"/>
        </header>"""

    response = gateway.post_xml("listaMesaje", payload)
    return Response(
        content=response.text,
        media_type="application/xml",
        status_code=response.status_code,
    )


@app.post(
    "/stare-mesaj",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def get_stare_mesaj(req: StareMesajRequest):
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
        <header xmlns="mfp:anaf:dgti:banci:reqStareMesaj:v1"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <listaMesaje index_incarcare="{req.index_incarcare}"/>
        </header>"""

    response = gateway.post_xml("stareMesaj", payload)
    return Response(
        content=response.text,
        media_type="application/xml",
        status_code=response.status_code,
    )


@app.post(
    "/descarcare-mesaj",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def download_mesaj(req: DescarcareMesajRequest):
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
        <header xmlns="mfp:anaf:dgti:banci:reqDescarcareMesaj:v1"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                id_portal="{req.id_portal}">
        </header>"""

    response = gateway.post_xml("descarcare", payload)
    return Response(
        content=response.text,
        media_type="application/xml",
        status_code=response.status_code,
    )


@app.post(
    "/upload-mesaj",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}}},
)
def upload_mesaj(req: UploadMesajRequest):
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
        <header xmlns="mfp:anaf:dgti:banci:reqUploadFisier:v1"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
            <upload fisier="{req.fisier_b64}"/>
        </header>"""

    response = gateway.post_xml("uploadMesaj", payload)
    return Response(
        content=response.text,
        media_type="application/xml",
        status_code=response.status_code,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
