# Admin dashboard

Web dashboard for operations staff (issue 022): approve or suspend drivers, view rides, and watch the live map.

## Run

Start the backend from the project root (set `AUTO_APPROVE_DRIVERS=false` to test approvals):

```powershell
$env:ADMIN_PHONES = "+919999999999"
$env:AUTO_APPROVE_DRIVERS = "false"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Then start the dashboard:

```powershell
cd admin
npm install
npm run dev
```

Open http://localhost:5173 and sign in with a number listed in `ADMIN_PHONES`. In dev the OTP is `123456`.

Set `VITE_API_URL` if the backend is not at http://localhost:8000.