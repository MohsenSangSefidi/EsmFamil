const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
const socket = new WebSocket(`${protocol}${window.location.host}/ws/game/${ROOM_CODE}/`);

// ---------- المان‌ها ----------
const letterStage = document.getElementById('letter-stage');
const wordsStage = document.getElementById('words-stage');
const reviewStage = document.getElementById('review-stage');
const scoresStage = document.getElementById('scores-stage');
const endStage = document.getElementById('end-stage');

const letterDisplay = document.getElementById('letter-display');
const gotItText = document.getElementById('got-it-text');
const gotItBtn = document.getElementById('got-it-btn');

const wordsLetter = document.getElementById('words-letter');
const wordsTimer = document.getElementById('words-timer');
const progressFill = document.getElementById('progress-fill');
const wordsForm = document.getElementById('words-form');
const finishBtn = document.getElementById('finish-btn');

const reviewFieldLabel = document.getElementById('review-field-label');
const reviewProgress = document.getElementById('review-progress');
const reviewProgressFill = document.getElementById('review-progress-fill');
const reviewContainer = document.getElementById('review-container');
const confirmNextBtn = document.getElementById('confirm-next-field-btn');
const confirmText = document.getElementById('confirm-text');

const scoreTable = document.getElementById('score-table');
const nextRoundBtn = document.getElementById('next-round-btn');
const finalScoreTable = document.getElementById('final-score-table');
const winnerDisplay = document.getElementById('winner-display');

// ---------- State ----------
let currentTimer = null;
let roundTime = 60;
let inputsLocked = false;
let letterConfirmed = false;
let wordsSubmitted = false;
let currentFieldData = null;

let myVotes = {};
let myConfirmedFieldIndex = -1;

// ---------- WebSocket ----------
socket.onopen = () => console.log('Game WS connected');
socket.onerror = (e) => console.error('WS error', e);

socket.onmessage = (e) => {
    const data = JSON.parse(e.data);
    console.log('Game event:', data);

    switch (data.type) {
        case 'letter_chosen':
            showLetterStage(data.letter);
            break;
        case 'got_it_update':
            updateGotItStatus(data.count, data.total);
            break;
        case 'word_entry_started':
            showWordsStage(data.letter, data.round_time);
            break;
        case 'round_ended':
            onRoundEnded();
            break;
        case 'review_field':
            showReviewField(data);
            break;
        case 'word_voted':
            applyVoteUpdate(data);
            break;
        case 'field_confirm_update':
            updateConfirmStatus(data.confirmed_count, data.total, data.session, data.confirmed);
            break;
        case 'scores_update':
            showScoresStage(data.scores);
            break;
        case 'game_ended':
            showEndStage(data.scores, data.winner);
            break;
        case 'error':
            alert(data.message);
            break;
    }
};

// =====================================================
//  مرحله حرف
// =====================================================
function showLetterStage(letter) {
    hideAllStages();
    letterStage.classList.remove('hidden');
    letterDisplay.textContent = letter;
    gotItText.textContent = 'همه باید «فهمیدم» بزنند';
    gotItBtn.disabled = false;
    gotItBtn.textContent = 'فهمیدم! ✅';
    letterConfirmed = false;

    gotItBtn.onclick = () => {
        if (letterConfirmed) return;
        letterConfirmed = true;
        socket.send(JSON.stringify({type: 'i_got_it'}));
        gotItBtn.disabled = true;
        gotItBtn.textContent = 'منتظر دیگران...';
    };
}

function updateGotItStatus(count, total) {
    if (letterConfirmed) gotItText.textContent = `${count} از ${total} نفر آماده‌اند`;
}

// =====================================================
//  مرحله کلمات
// =====================================================
function showWordsStage(letter, time) {
    hideAllStages();
    wordsStage.classList.remove('hidden');
    wordsLetter.textContent = letter;
    roundTime = time;

    document.querySelectorAll('.word-input').forEach(inp => {
        inp.value = '';
        inp.disabled = false;
        inp.classList.remove('input-empty');
    });
    inputsLocked = false;
    wordsSubmitted = false;
    progressFill.style.width = '100%';
    document.querySelector('.word-input')?.focus();

    // به‌روزرسانی دکمه (همه خالی → غیرفعال)
    updateFinishButtonState();

    startWordsTimer(onWordsTimeout);
}

// هر بار کاربر تایپ کرد → وضعیت دکمه را به‌روز کن
wordsForm.addEventListener('input', (e) => {
    if (e.target.classList.contains('word-input')) {
        updateFinishButtonState();
    }
});

// چک می‌کند همه پر هستند یا نه + دکمه را enable/disable می‌کند
function updateFinishButtonState() {
    if (inputsLocked || wordsSubmitted) return; // وضعیت قفل را دست نزن

    const inputs = document.querySelectorAll('.word-input');
    const emptyCount = [...inputs].filter(inp => !inp.value.trim()).length;

    if (emptyCount > 0) {
        finishBtn.disabled = true;
        finishBtn.textContent = `تمام کردم! 🏁 (${emptyCount} فیلد خالی)`;
    } else {
        finishBtn.disabled = false;
        finishBtn.textContent = 'تمام کردم! 🏁';
    }
}

// ارسال دستی — فقط اگر همه پر باشند
wordsForm.addEventListener('submit', (e) => {
    e.preventDefault();
    if (inputsLocked || wordsSubmitted) return;

    const words = collectWords();
    const emptyCount = Object.values(words).filter(v => !v).length;
    if (emptyCount > 0) {
        // این‌جا باید غیرقابل دسترس باشد چون دکمه غیرفعال است،
        // اما به‌عنوان لایه‌ی دفاعی دوم نگه می‌داریم.
        alert(`لطفاً ${emptyCount} فیلد خالی را پر کنید`);
        return;
    }

    wordsSubmitted = true;
    socket.send(JSON.stringify({type: 'i_finished', words, force: false}));
    lockInputs();
});

function collectWords() {
    const words = {};
    document.querySelectorAll('.word-input').forEach(inp => {
        words[inp.dataset.field] = inp.value.trim();
    });
    return words;
}

// تایمر تمام شد — راند باید اجباراً تمام شود، حتی با فیلدهای خالی
function onWordsTimeout() {
    if (inputsLocked || wordsSubmitted) return;
    wordsSubmitted = true;
    socket.send(JSON.stringify({type: 'i_finished', words: collectWords(), force: true}));
    lockInputs();
}

// یکی دیگر راند را تمام کرد — اجباراً ارسال کن (راند در حال بسته شدن است)
function onRoundEnded() {
    if (!wordsSubmitted && !inputsLocked && !wordsStage.classList.contains('hidden')) {
        wordsSubmitted = true;
        socket.send(JSON.stringify({type: 'i_finished', words: collectWords(), force: true}));
    }
    lockInputs();
    finishBtn.textContent = 'راند تمام شد';
}

function lockInputs() {
    if (inputsLocked) return;
    inputsLocked = true;
    document.querySelectorAll('.word-input').forEach(inp => inp.disabled = true);
    finishBtn.disabled = true;
    if (!wordsSubmitted) finishBtn.textContent = 'منتظر دیگران...';
    if (currentTimer) clearInterval(currentTimer);
}

function startWordsTimer(onEnd) {
    if (currentTimer) clearInterval(currentTimer);
    let remaining = roundTime;
    const total = roundTime;
    wordsTimer.textContent = formatTime(remaining);
    wordsTimer.classList.remove('warning');

    currentTimer = setInterval(() => {
        remaining--;
        wordsTimer.textContent = formatTime(remaining);
        progressFill.style.width = `${Math.max(0, (remaining / total) * 100)}%`;
        if (remaining <= 10) wordsTimer.classList.add('warning');
        if (remaining <= 0) {
            clearInterval(currentTimer);
            onEnd();
        }
    }, 1000);
}

// =====================================================
//  داوری
// =====================================================
function showReviewField(data) {
    hideAllStages();
    reviewStage.classList.remove('hidden');

    currentFieldData = data;
    reviewFieldLabel.textContent = data.field_label;
    reviewProgress.textContent = `فیلد ${data.field_index + 1} از ${data.total_fields}`;
    reviewProgressFill.style.width = `${((data.field_index + 1) / data.total_fields) * 100}%`;

    myConfirmedFieldIndex = -1;
    confirmNextBtn.textContent = 'تایید و فیلد بعدی ✅';
    confirmNextBtn.classList.remove('btn-success');
    confirmNextBtn.classList.add('btn-secondary');
    updateConfirmText(data.confirmed_count, data.total_players);

    myVotes = {};
    (data.submissions || []).forEach(sub => {
        const v = (sub.votes || []).find(vv => vv.voter === CURRENT_SESSION);
        if (v) myVotes[sub.id] = v.vote;
    });

    reviewContainer.innerHTML = '';
    const subs = data.submissions || [];

    if (subs.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'review-empty';
        empty.textContent = 'هیچ کلمه‌ای برای این فیلد ثبت نشده';
        reviewContainer.appendChild(empty);
        return;
    }

    subs.forEach(sub => {
        reviewContainer.appendChild(buildReviewCard(sub, data.my_session));
    });
}

function buildReviewCard(sub, mySession) {
    const card = document.createElement('div');
    card.className = 'review-item';
    card.id = `sub-${sub.id}`;
    if (sub.is_accepted === false) card.classList.add('rejected');
    if (sub.is_duplicate) card.classList.add('duplicate-flagged');

    const isOwn = sub.player_session === mySession;
    const isEmpty = !sub.value;
    const isRejected = sub.is_accepted === false;
    const myVote = myVotes[sub.id];

    // --- ستون بازیکن ---
    const playerEl = document.createElement('div');
    playerEl.className = 'review-player';
    const avatar = document.createElement('div');
    avatar.className = 'avatar-small';
    avatar.textContent = (sub.player_name || '?').charAt(0);
    const nameEl = document.createElement('span');
    nameEl.className = 'player-name';
    nameEl.textContent = sub.player_name;
    playerEl.appendChild(avatar);
    playerEl.appendChild(nameEl);
    card.appendChild(playerEl);

    // --- ستون کلمه + بج‌ها ---
    const wordArea = document.createElement('div');
    wordArea.className = 'review-word-area';

    const wordEl = document.createElement('span');
    wordEl.className = 'word-value';
    if (isEmpty) {
        wordEl.innerHTML = '<span class="empty-word">(خالی)</span>';
    } else {
        wordEl.textContent = sub.value;
        if (isRejected) wordEl.classList.add('struck');
    }
    wordArea.appendChild(wordEl);

    const badges = document.createElement('div');
    badges.className = 'word-badges';
    if (isRejected) badges.appendChild(makeBadge('danger', '🗑 حذف شده'));
    if (sub.is_duplicate) badges.appendChild(makeBadge('warning', '♻️ تکراری'));
    if (isOwn) badges.appendChild(makeBadge('primary', '👤 کلمه‌ی شما'));
    if (isEmpty && !isOwn) badges.appendChild(makeBadge('muted', 'خالی'));
    if (badges.children.length) wordArea.appendChild(badges);

    card.appendChild(wordArea);

    // --- ستون دکمه‌ها ---
    const actions = document.createElement('div');
    actions.className = 'review-actions';

    if (!isOwn && !isEmpty) {
        const rejectBtn = document.createElement('button');
        rejectBtn.type = 'button';
        rejectBtn.className = 'vote-btn reject';
        const rc = sub.reject_count || 0;
        rejectBtn.innerHTML = `🗑 حذف${rc > 0 ? `<span class="vote-count">${rc}</span>` : ''}`;
        if (myVote === 'reject') rejectBtn.classList.add('active');
        rejectBtn.onclick = () => toggleReject(sub.id, rejectBtn);
        actions.appendChild(rejectBtn);

        if (IS_HOST) {
            const dupBtn = document.createElement('button');
            dupBtn.type = 'button';
            dupBtn.className = 'vote-btn duplicate';
            dupBtn.innerHTML = sub.is_duplicate ? '✅ لغو تکراری' : '♻️ تکراری';
            if (sub.is_duplicate) dupBtn.classList.add('active');
            dupBtn.dataset.duplicate = sub.is_duplicate ? 'true' : 'false';
            dupBtn.onclick = () => toggleDuplicate(sub.id, dupBtn);
            actions.appendChild(dupBtn);
        }
    }

    if (actions.children.length) card.appendChild(actions);
    return card;
}

function makeBadge(kind, text) {
    const b = document.createElement('span');
    b.className = `badge badge-${kind}`;
    b.textContent = text;
    return b;
}

function toggleReject(submissionId, btn) {
    if (btn.disabled) return;
    btn.disabled = true;
    socket.send(JSON.stringify({
        type: 'vote_word',
        submission_id: submissionId,
        vote: myVotes[submissionId] === 'reject' ? 'clear_reject' : 'set_reject',
    }));
}

function toggleDuplicate(submissionId, btn) {
    if (btn.disabled) return;
    const isDup = btn.dataset.duplicate === 'true';
    btn.disabled = true;
    socket.send(JSON.stringify({
        type: 'vote_word',
        submission_id: submissionId,
        vote: isDup ? 'clear_duplicate' : 'set_duplicate',
    }));
}

function applyVoteUpdate(data) {
    if (!currentFieldData) return;

    const sub = (currentFieldData.submissions || [])
        .find(s => s.id === data.submission_id);
    if (!sub) return;

    // state مشترک
    sub.is_accepted = data.is_rejected ? false : null;
    sub.is_duplicate = data.is_duplicate;
    sub.reject_count = data.reject_count;

    // فقط اگر خودم رأی دادم/پس گرفتم، «رأی من» را تغییر بده
    if (data.actor_session === CURRENT_SESSION) {
        if (data.action === 'set_reject') {
            myVotes[sub.id] = 'reject';
        } else if (data.action === 'clear_reject') {
            delete myVotes[sub.id];
        }
    }

    const oldCard = document.getElementById(`sub-${sub.id}`);
    if (oldCard) {
        const newCard = buildReviewCard(sub, currentFieldData.my_session);
        oldCard.replaceWith(newCard);
    }
}

function updateConfirmText(count, total) {
    confirmText.textContent = `${count} از ${total} نفر تایید کرده‌اند`;
}

function updateConfirmStatus(count, total, session, confirmed) {
    updateConfirmText(count, total);
    if (session === CURRENT_SESSION) {
        if (confirmed) {
            confirmNextBtn.textContent = `منتظر دیگران... (${count}/${total})`;
            confirmNextBtn.classList.remove('btn-secondary');
            confirmNextBtn.classList.add('btn-success');
        } else {
            confirmNextBtn.textContent = 'تایید و فیلد بعدی ✅';
            confirmNextBtn.classList.remove('btn-success');
            confirmNextBtn.classList.add('btn-secondary');
        }
    } else {
        if (myConfirmedFieldIndex >= 0) {
            confirmNextBtn.textContent = `منتظر دیگران... (${count}/${total})`;
        }
    }
}

confirmNextBtn.addEventListener('click', () => {
    if (!currentFieldData) return;
    if (myConfirmedFieldIndex === currentFieldData.field_index) {
        myConfirmedFieldIndex = -1;
    } else {
        myConfirmedFieldIndex = currentFieldData.field_index;
    }
    socket.send(JSON.stringify({type: 'confirm_next_field'}));
});

// =====================================================
//  امتیازات / پایان
// =====================================================
function showScoresStage(scores) {
    hideAllStages();
    scoresStage.classList.remove('hidden');
    const tbody = scoreTable.querySelector('tbody');
    tbody.innerHTML = '';
    scores.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${escapeHtml(p.name)} ${p.is_host ? '👑' : ''}</td><td>${p.total_score}</td>`;
        tbody.appendChild(tr);
    });
    nextRoundBtn.classList.toggle('hidden', !IS_HOST);
}

nextRoundBtn.addEventListener('click', () => {
    nextRoundBtn.disabled = true;
    socket.send(JSON.stringify({type: 'next_round'}));
    setTimeout(() => nextRoundBtn.disabled = false, 1500);
});

function showEndStage(scores, winner) {
    hideAllStages();
    endStage.classList.remove('hidden');
    winnerDisplay.textContent = winner
        ? `🏆 برنده: ${winner.name} با ${winner.total_score} امتیاز`
        : 'بازی تمام شد';
    const tbody = finalScoreTable.querySelector('tbody');
    tbody.innerHTML = '';
    scores.forEach((p, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${i + 1}</td><td>${escapeHtml(p.name)}</td><td>${p.total_score}</td>`;
        tbody.appendChild(tr);
    });
}

// =====================================================
//  کمکی
// =====================================================
function hideAllStages() {
    [letterStage, wordsStage, reviewStage, scoresStage, endStage]
        .forEach(el => el && el.classList.add('hidden'));
}

function formatTime(sec) {
    const m = Math.floor(Math.max(0, sec) / 60);
    const s = Math.max(0, sec) % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}