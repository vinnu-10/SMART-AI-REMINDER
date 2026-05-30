# 🧠 Smart AI Reminder Agent

An intelligent reminder management system powered by AI, voice recognition, email notifications, and natural language processing.

The Smart AI Reminder Agent allows users to create reminders using natural language commands or voice input. The system automatically interprets dates and times, schedules reminders, sends email notifications, and provides real-time browser alerts.

---

## 🚀 Features

### 🔐 User Authentication

* User Registration
* Secure Login & Logout
* Password Hashing
* Session Management

### 🤖 AI-Powered Reminder Parsing

* Gemini AI Integration
* Natural Language Understanding
* Automatic Extraction of:

  * Reminder Title
  * Description
  * Date & Time
  * Email Address
  * Recurrence Pattern

### 🎤 Voice Recognition

* Speech-to-Text Reminder Creation
* Microphone Support
* Voice-Based Date and Time Input

### ⏰ Smart Scheduling

* One-Time Reminders
* Daily Recurring Reminders
* Weekly Recurring Reminders
* Multiple Occurrence Scheduling

### 📧 Email Notifications

* Gmail SMTP Integration
* Automated Reminder Emails
* Custom Reminder Messages

### 🔔 Real-Time Notifications

* Browser Notifications
* Voice Announcements
* Live Updates using Flask-SocketIO

### 🗄️ Database Management

* SQLite Database
* User Records
* Reminder Storage
* Reminder Status Tracking

### 🎨 Modern User Interface

* Responsive Design
* Bootstrap 5
* Pastel Theme
* Mobile Friendly Dashboard

---

## 🏗️ System Architecture

User → Voice/Text Input → Gemini AI Parser → Date Parser → Scheduler → Database → Email Service → Browser Notification

---

## 🛠️ Technologies Used

### Backend

* Python
* Flask
* Flask-SocketIO
* APScheduler
* SQLite

### AI & NLP

* Google Gemini API
* DateParser

### Frontend

* HTML
* CSS
* Bootstrap 5
* JavaScript

### Notifications

* Gmail SMTP
* Browser Notifications
* Speech Synthesis API

---

## 📂 Project Structure

```text
SMART-AI-REMINDER/
│
├── app.py                 # Main Flask Application
├── AGENT.py               # Gemini AI Reminder Agent
├── reminders.db           # SQLite Database
├── reminders.db.bak       # Database Backup
├── .env                   # Environment Variables
├── README.md
│
└── templates/
    ├── Login Page
    ├── Signup Page
    ├── Dashboard
    ├── Reminder Forms
    └── Notification Pages
```

---

## ⚙️ Installation

### Clone Repository

```bash
git clone https://github.com/yourusername/SMART-AI-REMINDER.git

cd SMART-AI-REMINDER
```

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Environment

Mac/Linux:

```bash
source venv/bin/activate
```

Windows:

```bash
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install flask
pip install flask-socketio
pip install apscheduler
pip install python-dotenv
pip install dateparser
pip install eventlet
pip install google-generativeai
pip install werkzeug
```

---

## 🔑 Environment Variables

Create a `.env` file:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY

GMAIL_USER=YOUR_GMAIL_ADDRESS

GMAIL_APP_PASSWORD=YOUR_GMAIL_APP_PASSWORD

FLASK_SECRET=YOUR_SECRET_KEY

PORT=5000
```

---

## ▶️ Run Application

```bash
python app.py
```

Open:

```text
http://localhost:5000
```

---

## 📋 Workflow

1. User logs into the system.
2. User creates reminder using text or voice.
3. Gemini AI extracts reminder details.
4. DateParser converts natural language to datetime.
5. Reminder stored in SQLite database.
6. APScheduler schedules task.
7. System sends email notification.
8. Browser notification and voice alert are triggered.

---

## 📸 Key Modules

### Authentication Module

* Signup
* Login
* Session Management

### AI Processing Module

* Natural Language Parsing
* Reminder Information Extraction

### Scheduling Module

* APScheduler
* Recurring Events

### Notification Module

* Email Alerts
* Browser Notifications
* Voice Announcements

### Database Module

* User Management
* Reminder Storage

---

## 🎯 Future Enhancements

* Mobile Application
* WhatsApp Notifications
* SMS Alerts
* Google Calendar Integration
* Multi-Language Support
* Cloud Deployment
* AI-Based Priority Prediction

---

## 📈 Applications

* Personal Task Management
* Student Study Reminders
* Meeting Scheduling
* Healthcare Appointment Alerts
* Project Deadline Tracking
* Business Task Automation

---

## 👨‍💻 Author
MUDIDE VINUTHNA

AI & Data Science Engineering

---

## 📜 License

This project is licensed under the MIT License.
