
document.getElementById("upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const res = await fetch("/upload/", {
        method: "POST",
        body: formData
    });
    const data = await res.json();
    window.currentFilename = data.filename;
    window.currentSubs = data.subtitles;
    subtitleData = data.subtitles;
    renderEditor();

    const video = document.getElementById("videoPlayer");
    startSubtitleSync(video);
});

document.getElementById("video-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const res = await fetch("/upload_video/", {
        method: "POST",
        body: formData
    });
    const data = await res.json();
    const video = document.getElementById("videoPlayer");
    video.src = data.video_url;
});

function renderEditor() {
    const container = document.getElementById("editor");
    container.innerHTML = "";
    currentSubs.forEach((line, index) => {
        const div = document.createElement("div");
        div.innerHTML = `
            <input value="${line.start}" data-index="${index}" data-key="start">
            <input value="${line.end}" data-index="${index}" data-key="end">
            <input value="${line.style}" data-index="${index}" data-key="style">
            <input value="${line.text}" data-index="${index}" data-key="text" style="width: 300px;">
        `;
        container.appendChild(div);
    });
}

function save() {
    document.querySelectorAll("#editor input").forEach(input => {
        const i = input.dataset.index;
        const key = input.dataset.key;
        currentSubs[i][key] = input.value;
    });

    fetch("/save/", {
        method: "POST",
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
            filename: window.currentFilename,
            data: JSON.stringify(currentSubs)
        })
    }).then(() => {
        window.location.href = "/download/" + window.currentFilename;
    });
}

let subtitleData = [];

function getColorByStyle(style) {
    const colors = {
        "John": "lightblue",
        "Mary": "lightpink",
        "Narrator": "lightgreen",
        "Default": "white"
    };
    return colors[style] || "white";
}

function startSubtitleSync(video) {
    const overlay = document.getElementById("subtitle-overlay");

    video.addEventListener("timeupdate", () => {
        const t = video.currentTime * 1000;
        const current = subtitleData.find(s => t >= parseInt(s.start) && t <= parseInt(s.end));
        if (current) {
            overlay.innerText = current.text;
            overlay.style.color = getColorByStyle(current.style);
        } else {
            overlay.innerText = "";
        }
    });
}


function registerRegions(wavesurfer) {
    const usedTimes = new Set();
    (window.currentSubs || []).forEach((line, index) => {
        let start = parseFloat(line.start) / 1000;
        let end = parseFloat(line.end) / 1000;

        let key = `${start.toFixed(3)}-${end.toFixed(3)}`;
        while (usedTimes.has(key)) {
            start += 0.01;
            end += 0.01;
            key = `${start.toFixed(3)}-${end.toFixed(3)}`;
        }
        usedTimes.add(key);

        const label = line.text?.slice(0, 30) || "Subtitle";

        wavesurfer.addRegion({
            id: `sub-${index}`,
            start,
            end,
            color: 'rgba(138, 43, 226, 0.2)',
            drag: true,
            resize: true,
            attributes: { title: label }
        });
    });
}
