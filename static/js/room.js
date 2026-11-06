const socket = new WebSocket(
    `ws://${window.location.host}/ws/room/${ROOM_CODE}/`
);

const playerList = document.getElementById('player-list');
const readyBtn = document.getElementById('ready-btn');
const startBtn = document.getElementById('start-btn');
const timeSetting = document.getElementById('time-setting');
const roundTimeInput = document.getElementById('round-time');
const roundTimeLabel = document.getElementById('round-time-label');
const copyBtn = document.getElementById('copy-code');

let isHost = false;
let isReady = false;

socket.onopen = () => {
    console.log('WebSocket connected');
};

socket.onmessage = (e) => {
    const data = JSON.parse(e.data);
    console.log('Received:', data);

    switch (data.type) {
        case 'room_update':
            updatePlayers(data.players, data.host_session);
            break;
        case 'all_ready':
            if (isHost) startBtn.classList.remove('hidden');
            break;
        case 'game_started':
            window.location.href = `/game/${ROOM_CODE}/`;
            break;
        case 'error':
            alert(data.message);
            break;
    }
};

socket.onerror = (e) => {
    console.error('WebSocket error:', e);
};

function updatePlayers(players, hostSession) {
    playerList.innerHTML = '';
    players.forEach(p => {
        const li = document.createElement('li');
        li.className = 'player-item';
        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = p.name.charAt(0);
        const nameSpan = document.createElement('span');
        nameSpan.className = 'player-name';
        nameSpan.textContent = p.name + (p.is_host ? ' 👑' : '');
        const statusSpan = document.createElement('span');
        statusSpan.className = 'player-status';
        if (p.is_ready) {
            statusSpan.innerHTML = '<span class="badge badge-success">آماده</span>';
        } else {
            statusSpan.innerHTML = '<span class="badge badge-warning">در انتظار</span>';
        }
        li.appendChild(avatar);
        li.appendChild(nameSpan);
        li.appendChild(statusSpan);
        playerList.appendChild(li);
    });

    // بررسی هاست بودن
    const myPlayer = players.find(p => p.is_host && p.name); // در واقعیت باید با session تطبیق داده شود
    // برای سادگی، از داده‌های ارسالی استفاده می‌کنیم
    isHost = hostSession === CURRENT_SESSION;
    if (isHost) {
        timeSetting.style.display = 'block';
    } else {
        timeSetting.style.display = 'none';
    }
}

readyBtn.addEventListener('click', () => {
    isReady = !isReady;
    socket.send(JSON.stringify({
        type: 'player_ready',
        is_ready: isReady,
    }));
    readyBtn.textContent = isReady ? 'لغو آمادگی' : 'آماده‌ام';
    readyBtn.classList.toggle('btn-success', isReady);
    readyBtn.classList.toggle('btn-primary', !isReady);
});

startBtn.addEventListener('click', () => {
    socket.send(JSON.stringify({ type: 'start_game' }));
});

roundTimeInput.addEventListener('input', (e) => {
    const val = e.target.value;
    roundTimeLabel.textContent = val;
    socket.send(JSON.stringify({
        type: 'set_round_time',
        round_time: parseInt(val),
    }));
});

copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(ROOM_CODE);
    copyBtn.textContent = '✅';
    setTimeout(() => copyBtn.textContent = '📋', 1500);
});