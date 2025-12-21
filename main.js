// Memento - Digital Legacy logic using REST API

class MementoApp {
    constructor() {
        this.apiUrl = 'http://localhost:5000/api';
        this.token = localStorage.getItem('memento_token') || null;
        this.currentUser = localStorage.getItem('memento_username') || null;
        this.authMode = 'login';

        this.timeLeft = 0;
        this.isSimulation = false;
        this.timerInterval = null;

        // DOM Elements
        this.authScreen = document.getElementById('authScreen');
        this.mainApp = document.getElementById('mainApp');
        this.authForm = document.getElementById('authForm');
        this.tabLogin = document.getElementById('tabLogin');
        this.tabSignup = document.getElementById('tabSignup');
        this.authSubmitBtn = document.getElementById('authSubmitBtn');
        this.displayUsername = document.getElementById('displayUsername');
        this.logoutBtn = document.getElementById('logoutBtn');
        this.timerDisplay = document.getElementById('timer');
        this.messageList = document.getElementById('messageList');
        this.messageModal = document.getElementById('messageModal');
        this.messageForm = document.getElementById('messageForm');
        this.simulationIndicator = document.getElementById('simulationIndicator');

        this.init();
    }

    async init() {
        this.setupEventListeners();
        if (this.token) {
            await this.refreshState();
            this.showApp();
        } else {
            this.showAuth();
        }
    }

    setupEventListeners() {
        this.tabLogin.onclick = () => this.switchAuthMode('login');
        this.tabSignup.onclick = () => this.switchAuthMode('signup');
        this.authForm.onsubmit = (e) => { e.preventDefault(); this.handleAuth(); };
        this.logoutBtn.onclick = () => this.logout();

        document.getElementById('IAmAliveBtn').onclick = () => this.sendHeartbeat();
        document.getElementById('addMessageBtn').onclick = () => this.openModal();
        document.getElementById('closeModal').onclick = () => this.closeModal();
        document.getElementById('toggleSimulation').onclick = () => this.toggleSimulation();
        document.getElementById('panicBtn').onclick = () => this.triggerPanic();

        this.messageForm.onsubmit = (e) => { e.preventDefault(); this.handleMessageSubmit(); };
    }

    // AUTH
    switchAuthMode(mode) {
        this.authMode = mode;
        this.tabLogin.classList.toggle('active', mode === 'login');
        this.tabSignup.classList.toggle('active', mode === 'signup');
        this.authSubmitBtn.textContent = mode === 'login' ? 'ENTER THE VAULT' : 'CREATE YOUR LEGACY';
    }

    async handleAuth() {
        const username = document.getElementById('authUsername').value;
        const password = document.getElementById('authPassword').value;
        const endpoint = this.authMode === 'login' ? '/login' : '/register';

        try {
            const resp = await fetch(this.apiUrl + endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await resp.json();

            if (resp.ok) {
                if (this.authMode === 'login') {
                    this.token = data.access_token;
                    this.currentUser = data.username;
                    localStorage.setItem('memento_token', this.token);
                    localStorage.setItem('memento_username', this.currentUser);
                    await this.refreshState();
                    this.showApp();
                } else {
                    alert("Account created. Please login.");
                    this.switchAuthMode('login');
                }
            } else {
                alert(data.msg || "Action failed");
            }
        } catch (err) {
            console.error(err);
            alert("Server connection error.");
        }
    }

    logout() {
        this.stopTimer();
        this.token = null;
        this.currentUser = null;
        localStorage.clear();
        this.showAuth();
    }

    showAuth() {
        this.authScreen.classList.remove('hidden');
        this.mainApp.classList.add('hidden');
    }

    showApp() {
        this.authScreen.classList.add('hidden');
        this.mainApp.classList.remove('hidden');
        this.displayUsername.textContent = `@${this.currentUser}`;
        this.renderMessages();
        this.startTimer();
    }

    // API SYNC
    async refreshState() {
        try {
            const resp = await fetch(this.apiUrl + '/status', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            if (resp.status === 401) return this.logout();
            const data = await resp.json();
            this.timeLeft = data.time_left;
            this.isSimulation = data.is_simulation;
            this.updateSimulationUI();
            this.updateTimerDisplay();
        } catch (err) { console.error("Poll failed", err); }
    }

    async sendHeartbeat() {
        try {
            await fetch(this.apiUrl + '/heartbeat', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            await this.refreshState();
            const btn = document.getElementById('IAmAliveBtn');
            btn.textContent = "HEARTBEAT RECEIVED";
            setTimeout(() => btn.textContent = "I AM ALIVE", 2000);
        } catch (err) { console.error(err); }
    }

    async toggleSimulation() {
        try {
            await fetch(this.apiUrl + '/toggle-simulation', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            await this.refreshState();
        } catch (err) { console.error(err); }
    }

    updateSimulationUI() {
        const btn = document.getElementById('toggleSimulation');
        btn.classList.toggle('active', this.isSimulation);
        btn.textContent = this.isSimulation ? "STOP SIMULATION" : "SIMULATION MODE";
        this.simulationIndicator.innerHTML = this.isSimulation ? '● SIMULATION ACTIVE' : '';
    }

    // TIMER
    startTimer() {
        if (this.timerInterval) clearInterval(this.timerInterval);
        this.timerInterval = setInterval(() => {
            if (this.timeLeft > 0) {
                this.timeLeft--;
                this.updateTimerDisplay();
            } else {
                this.triggerDeathEvent();
            }
        }, 1000);
    }

    stopTimer() { clearInterval(this.timerInterval); }

    updateTimerDisplay() {
        const h = Math.floor(this.timeLeft / 3600);
        const m = Math.floor((this.timeLeft % 3600) / 60);
        const s = this.timeLeft % 60;
        this.timerDisplay.textContent = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        this.timerDisplay.style.color = this.timeLeft < 3600 ? 'var(--danger-color)' : 'var(--text-primary)';
    }

    triggerDeathEvent() {
        this.stopTimer();
        alert("DEAD MAN SWITCH TRIGGERED: Sending legacy messages...");
    }

    triggerPanic() {
        if (confirm("Immediate dispatch of ALL messages?")) {
            this.triggerDeathEvent();
        }
    }

    // MESSAGES
    async renderMessages() {
        const resp = await fetch(this.apiUrl + '/messages', {
            headers: { 'Authorization': `Bearer ${this.token}` }
        });
        const msgs = await resp.json();
        this.messageList.innerHTML = msgs.length === 0 ? '<p style="text-align:center; color:gray">Vault is empty</p>' : '';
        msgs.forEach(m => {
            const div = document.createElement('div');
            div.className = 'message-card';
            div.innerHTML = `
                <div>
                    <h4>${m.recipient}</h4>
                    <span class="recipient-badge">${m.channel}</span>
                </div>
                <div>
                    <button class="btn" onclick="app.openModal(${JSON.stringify(m).replace(/"/g, '&quot;')})">Edit</button>
                    <button class="btn" style="color:red" onclick="app.deleteMessage(${m.id})">Del</button>
                </div>
            `;
            this.messageList.appendChild(div);
        });
    }

    openModal(msg = null) {
        document.getElementById('editIndex').value = msg ? msg.id : "";
        document.getElementById('recipient').value = msg ? msg.recipient : "";
        document.getElementById('channel').value = msg ? msg.channel : "Email";
        document.getElementById('contact').value = msg ? msg.contact : "";
        document.getElementById('message').value = msg ? msg.text : "";
        this.messageModal.style.display = 'flex';
    }

    closeModal() { this.messageModal.style.display = 'none'; }

    async handleMessageSubmit() {
        const id = document.getElementById('editIndex').value;
        const msgData = {
            recipient: document.getElementById('recipient').value,
            channel: document.getElementById('channel').value,
            contact: document.getElementById('contact').value,
            text: document.getElementById('message').value
        };

        const method = id ? 'PUT' : 'POST';
        const url = id ? `${this.apiUrl}/messages/${id}` : `${this.apiUrl}/messages`;

        await fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.token}`
            },
            body: JSON.stringify(msgData)
        });
        this.closeModal();
        this.renderMessages();
    }

    async deleteMessage(id) {
        if (confirm("Delete this message?")) {
            await fetch(`${this.apiUrl}/messages/${id}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            this.renderMessages();
        }
    }
}

const app = new MementoApp();
window.app = app;
