import requests, urllib3, os
urllib3.disable_warnings()

BASE     = "https://reclutapp-prod-dkhggmfdgrckdkeq.westeurope-01.azurewebsites.net"
DB_LOCAL = r"c:\Users\jjbustos\OneDrive - Grupo Jerónimo Martins\Documents\NOMINA_GIT\reclutapp\data\reclutapp.db"

r = requests.post(f"{BASE}/api/auth/login",
    json={"email": "jeysshon.bustos@jeronimo-martins.com", "password": "Jey@*1019"}, verify=False)
r.raise_for_status()
token = r.json()["access_token"]
print("Login OK")

size_mb = os.path.getsize(DB_LOCAL) / 1024 / 1024
print(f"Subiendo {size_mb:.1f} MB ...")

with open(DB_LOCAL, "rb") as f:
    r = requests.post(
        f"{BASE}/api/admin/upload-db",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
        data=f,
        verify=False,
        timeout=300,
    )

print(f"Status: {r.status_code}")
print(f"Body: {r.text[:500]}")
