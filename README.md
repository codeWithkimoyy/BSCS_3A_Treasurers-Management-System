# BSCS 3-A Treasurer's Management System

A web-based student treasurer application for managing event-based payment collections, student records, and financial reporting.

## Features

- **Event-based Payment Collection** — Create events, mark students as paid, confirm and lock payments
- **Student Management** — Add, edit, and manage student records with active/inactive status
- **Transaction Tracking** — Record general income and expenses with full audit trail
- **Google Sign-In** — OAuth 2.0 authentication via Google Identity Services
- **Role-based Access** — Admin, Mayor, Treasurer, and Staff roles with granular permissions
- **Reporting** — Summary reports, per-student breakdowns, date-range filtering, CSV export
- **Mobile Responsive** — Touch-friendly interface with mobile bottom navigation

## Tech Stack

- **Backend:** Python, Flask, PyMongo
- **Database:** MongoDB Atlas
- **Auth:** Google Identity Services (GIS) + Flask-Login
- **Frontend:** Bootstrap 5, DataTables, Chart.js
- **Deployment:** Render

## Setup

### Prerequisites
- Python 3.14+
- MongoDB instance (local or Atlas)

### Local Development

1. Clone the repo:
```bash
git clone https://github.com/codeWithkimoyy/BSCS_3A_Treasurers-Management-System.git
cd BSCS_3A_Treasurers-Management-System
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file in project root:
```env
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/student_treasury
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
SECRET_KEY=your-random-secret-key
```

4. Run the app:
```bash
python app.py
```

5. Visit `http://localhost:5000` — default admin login: `admin` / `admin123`

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MONGO_URI` | Yes | MongoDB connection string |
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth 2.0 Client ID |
| `SECRET_KEY` | No | Flask session key (auto-generated if empty) |

## Deployment

Deployed on Render. Push to `main` branch triggers auto-deploy.

## License

MIT
