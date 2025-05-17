from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse
import json, os
import pandas as pd
import urllib.parse


from typing import List

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="secret-key")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/subtitles", StaticFiles(directory="subtitles"), name="subtitles")
templates = Jinja2Templates(directory="templates")

USERS_FILE = "users.json"
ASSIGNMENTS_FILE = "assignments.json"

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)

if not os.path.exists(ASSIGNMENTS_FILE):
    with open(ASSIGNMENTS_FILE, "w") as f:
        json.dump({}, f)

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def load_assignments():
    with open(ASSIGNMENTS_FILE, "r") as f:
        return json.load(f)

def save_assignments(assignments):
    with open(ASSIGNMENTS_FILE, "w") as f:
        json.dump(assignments, f, indent=2)

@app.api_route("/login", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    users = load_users()
    user = users.get(username)
    if user and user["password"] == password:
        request.session["user"] = {"username": username, "role": user["role"]}
        return RedirectResponse("/projects", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/login")

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse("/login")
    
    # Load all projects
    root_dir = "subtitles"
    projects = []
    if os.path.exists(root_dir):
        for name in os.listdir(root_dir):
            if os.path.isdir(os.path.join(root_dir, name)):
                projects.append(name)

    # Load all users
    users_dict = load_users()
    users = [{"username": uname, "role": data["role"]} for uname, data in users_dict.items()]

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "projects": projects,
        "users": users
    })

@app.get("/admin/project_episodes")
async def get_project_episodes(project: str):
    import os
    project_path = os.path.join("subtitles", project)
    episodes = []

    if os.path.isdir(project_path):
        for folder in os.listdir(project_path):
            ep_path = os.path.join(project_path, folder)
            if os.path.isdir(ep_path):
                base_path = os.path.join(ep_path, folder)
                episodes.append({
                    "name": folder,
                    "has_video": os.path.isfile(base_path + ".mp4"),
                    "has_csv_en": os.path.isfile(base_path + "_en.csv"),
                    "has_csv_ar": os.path.isfile(base_path + "_ar.csv")
                })

    return {"episodes": episodes}

@app.get("/admin/assigned_users")
async def get_assigned_users(project: str, episode: str):
    assignments = load_assignments()
    key = f"{project}/{episode}"
    users = assignments.get(key, [])
    return {"users": users}

@app.post("/admin/assign_user")
async def assign_user(title: str = Form(...), episode: str = Form(...), username: str = Form(...)):
    assignments = load_assignments()
    key = f"{title}/{episode}"
    if key not in assignments:
        assignments[key] = []
    if username not in assignments[key]:
        assignments[key].append(username)
    save_assignments(assignments)
    return {"status": "assigned"}

@app.post("/admin/remove_assignment")
async def remove_assignment(project: str = Form(...), episode: str = Form(...), username: str = Form(...)):
    assignments = load_assignments()
    key = f"{project}/{episode}"
    if key in assignments and username in assignments[key]:
        assignments[key].remove(username)
        save_assignments(assignments)
    return {"status": "removed"}

@app.post("/admin/create_user")
async def create_user(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form(...)):
    session_user = request.session.get("user")
    if not session_user or session_user.get("role") != "admin":
        return RedirectResponse("/login", status_code=302)

    users = load_users()
    if username in users:
        return templates.TemplateResponse("admin.html", {
            "request": request,
            "projects": [],
            "users": [],
            "user_exists": username
        })

    users[username] = {"password": password, "role": role}
    save_users(users)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "projects": [],
        "users": [],
        "user_created": username
    })


#------------------------------------------------------------------------------------------------------------

def timecode_to_seconds(tc):
    h, m, s, f = map(int, tc.split(":"))
    return h * 3600 + m * 60 + s + f / 25

def timecode_filter(seconds):
    fps = 25
    total_frames = int(round(seconds * fps))
    h = total_frames // (3600 * fps)
    m = (total_frames // (60 * fps)) % 60
    s = (total_frames // fps) % 60
    f = total_frames % fps
    return f"{h:02}:{m:02}:{s:02}:{f:02}"

templates.env.filters["timecode"] = timecode_filter

@app.get("/editor/{project}/{episode}", response_class=HTMLResponse)
async def subtitle_editor(request: Request, project: str, episode: str):
    decoded_project = urllib.parse.unquote(project)
    decoded_episode = urllib.parse.unquote(episode)

    # Auto-create missing CSV (EN or AR)
    base_path = os.path.join("subtitles", decoded_project, decoded_episode)
    en_path = os.path.join(base_path, f"{decoded_episode}_en.csv")
    ar_path = os.path.join(base_path, f"{decoded_episode}_ar.csv")
    if os.path.exists(en_path) and not os.path.exists(ar_path):
        df = pd.read_csv(en_path, encoding="utf-8-sig")
        df_out = df[["Timecode In", "Timecode Out", "Character"]].copy()
        df_out["Dialogue"] = ""
        df_out.to_csv(ar_path, index=False, encoding="utf-8-sig")
    elif os.path.exists(ar_path) and not os.path.exists(en_path):
        df = pd.read_csv(ar_path, encoding="utf-8-sig")
        df_out = df[["Timecode In", "Timecode Out", "Character"]].copy()
        df_out["Dialogue"] = ""
        df_out.to_csv(en_path, index=False, encoding="utf-8-sig")

    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")

    decoded_project = urllib.parse.unquote(project)
    decoded_episode = urllib.parse.unquote(episode)
    base_path = os.path.join("subtitles", decoded_project, decoded_episode)
    en_path = os.path.join(base_path, f"{decoded_episode}_en.csv")
    ar_path = os.path.join(base_path, f"{decoded_episode}_ar.csv")
    edits_path = os.path.join(base_path, f"{decoded_episode}_edits.json")

    df_en = pd.read_csv(en_path, encoding="utf-8-sig") if os.path.exists(en_path) else None
    df_ar = pd.read_csv(ar_path, encoding="utf-8-sig") if os.path.exists(ar_path) else None

    edits = {}
    if os.path.exists(edits_path):
        with open(edits_path, "r", encoding="utf-8") as f:
            edits = json.load(f)

    if df_en is not None:
        df_en.columns = df_en.columns.str.strip().str.replace("﻿", "")
        df_en["start"] = df_en["Timecode In"].apply(timecode_to_seconds)
        df_en["end"] = df_en["Timecode Out"].apply(timecode_to_seconds)
        df_en["speaker"] = df_en["Character"].fillna("English").replace("", "English")
        df_en["text"] = df_en["Dialogue"].fillna("").str.replace("\n", " ", regex=False)
        df_en["text"] = df_en["text"].astype(str)
        for i in range(len(df_en)):
            key = f"{i}-en"
            if key in edits:
                df_en.at[i, "text"] = edits[key]

    if df_ar is not None:
        df_ar.columns = df_ar.columns.str.strip().str.replace("﻿", "")
        df_ar["start"] = df_ar["Timecode In"].apply(timecode_to_seconds)
        df_ar["end"] = df_ar["Timecode Out"].apply(timecode_to_seconds)
        df_ar["speaker"] = df_ar["Character"].fillna("Arabic").replace("", "Arabic")
        df_ar["text"] = df_ar["Dialogue"].fillna("").str.replace("\n", " ", regex=False)
        df_ar["text"] = df_ar["text"].astype(str)
        for i in range(len(df_ar)):
            key = f"{i}-ar"
            if key in edits:
                df_ar.at[i, "text"] = edits[key]

    paired_lines = []
    length = max(len(df_en) if df_en is not None else 0, len(df_ar) if df_ar is not None else 0)
    for i in range(length):
        en_row = df_en.iloc[i] if df_en is not None and i < len(df_en) else None
        ar_row = df_ar.iloc[i] if df_ar is not None and i < len(df_ar) else None
        start = en_row["start"] if en_row is not None else ar_row["start"]
        end = en_row["end"] if en_row is not None else ar_row["end"]
        en_data = {"speaker": en_row["speaker"], "text": en_row["text"]} if en_row is not None else {"speaker": "English", "text": ""}
        ar_data = {"speaker": ar_row["speaker"], "text": ar_row["text"]} if ar_row is not None else {"speaker": "Arabic", "text": ""}
        paired_lines.append({"start": start, "end": end, "en": en_data, "ar": ar_data})

    colors = ["#E91E63", "#3F51B5", "#4CAF50", "#FF9800", "#9C27B0", "#009688", "#795548", "#607D8B"]
    speaker_colors = {}
    for pair in paired_lines:
        for side in ["en", "ar"]:
            name = pair[side]["speaker"]
            if name not in speaker_colors:
                speaker_colors[name] = colors[len(speaker_colors) % len(colors)]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "project": decoded_project,
        "episode": decoded_episode,
        "paired_lines": paired_lines,
        "speaker_colors": speaker_colors
    })

@app.post("/save_edits")
async def save_edits(index: int = Form(...), lang: str = Form(...), text: str = Form(...), project: str = Form(...), episode: str = Form(...)):
    path = os.path.join("subtitles", project, episode)
    os.makedirs(path, exist_ok=True)
    edits_path = os.path.join(path, f"{episode}_edits.json")

    if os.path.exists(edits_path):
        with open(edits_path, "r", encoding="utf-8") as f:
            edits = json.load(f)
    else:
        edits = {}

    key = f"{index}-{lang}"
    edits[key] = text

    with open(edits_path, "w", encoding="utf-8") as f:
        json.dump(edits, f, ensure_ascii=False, indent=2)

    return {"status": "saved", "key": key}

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/edits")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse("/login")

    # Load available projects and users
    root_dir = "subtitles"
    projects = []
    if os.path.exists(root_dir):
        for project_name in os.listdir(root_dir):
            if os.path.isdir(os.path.join(root_dir, project_name)):
                projects.append(project_name)

    users_dict = load_users()
    users = [{"username": name, "role": data["role"]} for name, data in users_dict.items()]

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "projects": projects,
        "users": users
    })

@app.post("/admin/create_project")
async def create_project(
    request: Request,
    project_select: str = Form(""),
    project_input: str = Form(""),
    episode_count: str = Form("0")
):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse("/login", status_code=302)

    # Determine the actual project name
    project_name = project_input.strip() or project_select.strip()
    if not project_name:
        return templates.TemplateResponse("admin.html", {
            "request": request,
            "projects": [],
            "users": [],
            "project_exists": "No project name provided"
        })

    path = os.path.join("subtitles", project_name)
    if not os.path.exists(path):
        os.makedirs(path)

    try:
        count = int(episode_count)
    except ValueError:
        count = 0

    created_episodes = []
    for i in range(1, count + 1):
        episode_folder = os.path.join(path, f"{project_name}_Episode_{i}")
        if not os.path.exists(episode_folder):
            os.makedirs(episode_folder)
            created_episodes.append(episode_folder)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "projects": [],
        "users": [],
        "project_created": project_name,
        "episode_created": len(created_episodes)
    })


@app.get("/admin/project_episodes")
async def get_project_episodes(project: str):
    import os
    project_path = os.path.join("subtitles", project)
    episodes = []

    if os.path.isdir(project_path):
        for folder in os.listdir(project_path):
            ep_path = os.path.join(project_path, folder)
            if os.path.isdir(ep_path):
                base_path = os.path.join(ep_path, folder)
                episodes.append({
                    "name": folder,
                    "has_video": os.path.isfile(base_path + ".mp4"),
                    "has_csv_en": os.path.isfile(base_path + "_en.csv"),
                    "has_csv_ar": os.path.isfile(base_path + "_ar.csv")
                })

    return {"episodes": episodes}









@app.get("/admin/project_episode_count")
async def project_episode_count(project: str):
    import os
    project_path = os.path.join("subtitles", project)
    count = 0
    if os.path.isdir(project_path):
        count = len([
            name for name in os.listdir(project_path)
            if os.path.isdir(os.path.join(project_path, name))
        ])
    return {"project": project, "count": count}


@app.get("/admin/debug_project_episodes")
async def debug_project_episodes(project: str):
    from fastapi.responses import JSONResponse
    import os

    project_path = os.path.join("subtitles", project)
    episodes = []

    if os.path.isdir(project_path):
        for folder in os.listdir(project_path):
            ep_path = os.path.join(project_path, folder)
            if os.path.isdir(ep_path):
                video_file = os.path.join(ep_path, f"{folder}.mp4")
                has_video = os.path.isfile(video_file)
                episodes.append({
                    "name": folder,
                    "has_video": has_video
                })

    return JSONResponse(content={"episodes": episodes})




@app.get("/admin/users", response_class=HTMLResponse)
async def list_users(request: Request):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse("/login")
    users = load_users()
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users
    })

@app.post("/admin/edit_user")
async def edit_user(username: str = Form(...)):
    # Placeholder for future editing logic
    return RedirectResponse("/admin/users", status_code=302)

@app.post("/admin/delete_user")
async def delete_user(username: str = Form(...)):
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
    return RedirectResponse("/admin/users", status_code=302)


@app.get("/projects", response_class=HTMLResponse)
async def view_projects(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login")

    base_dir = "subtitles"
    assignments = load_assignments()
    projects = {}

    for key, assigned_users in assignments.items():
        project, episode = key.split("/", 1)
        if user["role"] == "admin" or user["username"] in assigned_users:
            if project not in projects:
                projects[project] = []
            projects[project].append({
                "name": episode,
                "users": assigned_users
            })

    return templates.TemplateResponse("projects.html", {
        "request": request,
        "username": user["username"],
        "role": user["role"],
        "projects": [
            {"title": project, "episodes": eps}
            for project, eps in projects.items()
        ]
    })


from fastapi.responses import FileResponse

def apply_edits_to_df(df, edits, lang_prefix):
    for i in range(len(df)):
        key = f"{i}-{lang_prefix}"
        if key in edits:
            df.at[i, "Dialogue"] = edits[key]
    return df

@app.get("/export")
async def export_en(project: str, episode: str):
    import os
    base = os.path.join("subtitles", project, episode)
    en_path = os.path.join(base, f"{episode}_en.csv")
    edits_path = os.path.join(base, f"{episode}_edits.json")
    final_path = os.path.join(base, f"{episode}_Final_en.csv")

    if not os.path.exists(en_path):
        return JSONResponse(status_code=404, content={"error": "English CSV not found"})
    df = pd.read_csv(en_path, encoding="utf-8-sig")
    if os.path.exists(edits_path):
        with open(edits_path, "r", encoding="utf-8") as f:
            edits = json.load(f)
        df = apply_edits_to_df(df, edits, "en")
    df.to_csv(final_path, index=False, encoding="utf-8-sig")
    return FileResponse(final_path, filename=f"{episode}_Final_en.csv")

@app.get("/export_ar")
async def export_ar(project: str, episode: str):
    import os
    base = os.path.join("subtitles", project, episode)
    ar_path = os.path.join(base, f"{episode}_ar.csv")
    edits_path = os.path.join(base, f"{episode}_edits.json")
    final_path = os.path.join(base, f"{episode}_Final_ar.csv")

    if not os.path.exists(ar_path):
        return JSONResponse(status_code=404, content={"error": "Arabic CSV not found"})
    df = pd.read_csv(ar_path, encoding="utf-8-sig")
    if os.path.exists(edits_path):
        with open(edits_path, "r", encoding="utf-8") as f:
            edits = json.load(f)
        df = apply_edits_to_df(df, edits, "ar")
    df.to_csv(final_path, index=False, encoding="utf-8-sig")
    return FileResponse(final_path, filename=f"{episode}_Final_ar.csv")

@app.get("/export_merged")
async def export_merged(project: str, episode: str):
    import os
    base = os.path.join("subtitles", project, episode)
    en_path = os.path.join(base, f"{episode}_en.csv")
    ar_path = os.path.join(base, f"{episode}_ar.csv")
    edits_path = os.path.join(base, f"{episode}_edits.json")
    final_path = os.path.join(base, f"{episode}_Final_merged.csv")

    if not (os.path.exists(en_path) and os.path.exists(ar_path)):
        return JSONResponse(status_code=404, content={"error": "Missing CSV files"})
    df_en = pd.read_csv(en_path, encoding="utf-8-sig")
    df_ar = pd.read_csv(ar_path, encoding="utf-8-sig")

    if os.path.exists(edits_path):
        with open(edits_path, "r", encoding="utf-8") as f:
            edits = json.load(f)
        df_en = apply_edits_to_df(df_en, edits, "en")
        df_ar = apply_edits_to_df(df_ar, edits, "ar")

    merged = pd.DataFrame({
        "Start": df_en["Timecode In"],
        "End": df_en["Timecode Out"],
        "Speaker_EN": df_en["Character"],
        "Text_EN": df_en["Dialogue"],
        "Speaker_AR": df_ar["Character"],
        "Text_AR": df_ar["Dialogue"]
    })

    merged.to_csv(final_path, index=False, encoding="utf-8-sig")
    return FileResponse(final_path, filename=f"{episode}_Final_merged.csv")