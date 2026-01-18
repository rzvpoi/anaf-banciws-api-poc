# ANAF BanciWS API integration (POC)

> **NOTE:**
> This is a proof of concept and not affiliated with or endorsed by ANAF or any specific organization.
Use at your own risk and ensure compliance with ANAF's terms of service.

## Description

This repository is a proof of concept that serves as a technical reference for integrating with ANAF’s BANCIWS REST services, when F5 Big-IP enforces browser-style session management, requiring a workaround for machine-to-machine communication.

Before performing any tests, it is strongly recommended to read this README and the official ANAF documentation in order to understand the integration flow and constraints imposed by the F5 Big-IP layer.

Official documentation from ANAF can be found [here](https://static.anaf.ro/static/IFN/instructiuni_ifn.html). Some of the documents are in this repo as well in case the link to ANAF becomes unavailable.

## Concept

This repository demonstrates a working proof of concept for integrating with ANAF’s `BANCIWS` REST services in the presence of an F5 Big‑IP APM layer. Unlike a typical REST API, the ANAF infrastructure is primarily designed for browser-based access, and direct machine-to-machine calls with client certificates (mTLS) are not supported by the current F5 access policy so a workaround is required to establish a session before making API requests.

The architecture can be described in three layers. The client initiates a TLS connection presenting a client certificate. This connection first reaches the F5 Big‑IP, which enforces browser-style access policies, including redirects and session management. Only after F5 establishes a valid session does the request reach the ANAF REST backend. F5’s design ensures that a standard API client without a prior session cannot communicate directly with the backend.

The key challenge arises because even a correctly configured client certificate and a valid TLS handshake are insufficient to satisfy the F5 access policy. The system responds with a series of `302` redirects to the `/my.policy` endpoint, issuing session cookies such as `MRHSession`, `LastMRH_Session`, and `F5_ST`. Without these cookies, subsequent requests are rejected, even if the TLS connection is valid. This behavior is intentional and not a misconfiguration.

To work around this, the client must first perform a dummy POST request to a valid endpoint, for example `listaMesaje`. This request allows F5 to build a session in the same manner it does for a browser, issuing the necessary cookies and following the redirect chain. Once the session is established, the client can replay real API requests using the same cookies and TLS session. At this point, backend calls behave as expected and return the normal XML responses.

Implementing this approach in any programming language follows a simple pattern. The client must support client certificates, cookie storage, and automatic handling of redirects. It performs an initial POST to establish the F5 session, capturing any cookies issued. Subsequent requests reuse the same cookies and TLS session to communicate with ANAF endpoints. This flow ensures compliance with F5’s session-based access policy without bypassing any security mechanisms.

Detecting authentication failure is straightforward. If the client receives a `200 OK` response containing HTML rather than XML, it likely indicates that the client certificate was not recognized by F5. Common HTML indicators include the presence of `<html>` tags, references to `/my.policy` or `vdesk`, and text such as “Certificatul nu a fost prezentat.” Any client receiving such a response should treat it as an authentication failure and retry the session establishment flow.

The POC covers all endpoints documented by ANAF, including `listaMesaje`, `stareMesaj`, `uploadMesaj`, and `descarcareMesaj`. All endpoints require correctly formatted XML payloads and adherence to ANAF’s XSD definitions. ANAF’s parsers are strict, and any deviation in namespace, attribute formatting, or encoding may result in `400 Bad Request` errors.

The workaround described here does not compromise security. All TLS handshakes remain valid, and the client certificate is fully verified by F5. The session established through the dummy POST is the same mechanism a browser would use. No credentials are bypassed, no TLS verification is disabled, and the backend is accessed only through authorized channels. However, this approach is fragile in the sense that changes to F5 policies or ANAF’s configuration may require updates to the client.

Integrating with ANAF through the F5 Big‑IP layer requires understanding that the system enforces browser-style session management. By establishing a session first and reusing the session cookies, clients can perform API calls reliably. This proof of concept provides a practical path for automation, but it remains dependent on the current infrastructure and should be considered experimental. Future changes to ANAF’s authentication mechanisms or support for proper mTLS for service accounts could render this workaround obsolete.

## High level architecture

```
Client (API / script / service)
        |
        |  mTLS (client certificate)
        v
+-------------------+
|   F5 Big‑IP APM   |
|  (Session-based)  |
+-------------------+
        |
        |  only after session is established
        v
+-------------------+
|  ANAF REST API    |
|  BANCIWS backend |
+-------------------+
```

## General algorithm

1. Create HTTP client with:
   - client certificate (mTLS)
   - cookie support
   - redirect support

2. POST dummy request to any valid endpoint
   - allow redirects
   - store cookies

3. Re-POST the real request
   - same URL
   - same cookies
   - same TLS session

4. Reuse the same client for all future calls, when session times out go to step 2.

## Prerequisites
- Python 3.8+
- `requests` and `FastAPI` libraries
- A valid ANAF client certificate (see [ANAF documentation]((https://static.anaf.ro/static/IFN/instructiuni_ifn.html)))

## Setup
1. Place your ANAF client certificate and key in the `certs/` directory.
2. Rename the files to `cert-anaf.pem` and `anaf-key.pem` (or update `CERT_PATH` and `KEY_PATH` in the code).


## Code Implementation

In `src/` folder you can find a simple gateway implementation in Python using FastAPI and requests. It exposes a small REST API that forwards calls to ANAF’s BANCIWS services while handling the F5 Big-IP session requirements transparently.

The gateway uses mTLS with the client certificate issued by ANAF. A single persistent HTTP session is maintained so that cookies issued by F5 Big-IP are reused across requests. This is required because F5 does not accept pure machine-to-machine mTLS and enforces a browser-style session instead. To learn how to get your certificate from ANAF go [here](https://static.anaf.ro/static/IFN/informatii_flux_extern_serviciu_web_masina_masina_test_IFN.pdf), or check the pdf in `BANCIWS_docs` directory.

All XML formats, namespaces, and structures are taken directly from ANAF’s official documentation. The relevant XSD files and examples can be found in the ./BANCIWS_docs folder. 

To run the api follow these steps:
1. Install libraries
```
pip install -r requirements.txt
```
2. Start the app
```
python3 anaf-ifn-gateway.py
```

## Troubleshooting
- If you receive HTML responses instead of XML, your client certificate may not be recognized by F5. Double-check the certificate and session establishment.
- If the session times out, the gateway will automatically re-authenticate.

It will start listening on (http://0.0.0.0:8000), to check the API documentation go to (http://0.0.0.0:8000/docs)

## License
This project is licensed under the [MIT License](LICENSE).

