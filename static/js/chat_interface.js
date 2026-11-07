/**
 * BashFlow Cloud - Baileys WhatsApp WebSocket & Chat Interface Module (chat_interface.js)
 * Phase 7: Frontend Decoupling & Modularization
 * Handles: Real-time Socket.IO Baileys events, message rendering, chat list switching,
 * chat bar listeners, audio/PTT voice playback, and mobile chat viewport transitions.
 */

(function(window, document) {
    'use strict';

    const BashFlowChat = {
        socket: null,
        reconnectAttempts: 0,
        activeChatId: null,
        chats: [],
        messages: [],

        init() {
            this.initSocket();
            this.initChatBarListeners();
            this.initMobileChatToggle();
        },

        initSocket() {
            if (typeof io === 'undefined' || this.socket) return;
            try {
                this.socket = io({
                    transports: ['polling', 'websocket'],
                    upgrade: true,
                    reconnection: true,
                    reconnectionAttempts: Infinity,
                    reconnectionDelay: 2000,
                    reconnectionDelayMax: 30000,
                    timeout: 12000
                });

                this.socket.on('connect', () => {
                    this.reconnectAttempts = 0;
                    console.log('[BashFlowChat] Real-time Baileys bridge socket connected.');
                    if (typeof setGlobalConnectionStatus === 'function') {
                        setGlobalConnectionStatus('connected');
                    }
                });

                this.socket.on('disconnect', (reason) => {
                    console.debug('[BashFlowChat] Socket disconnected:', reason);
                });

                this.socket.on('new_whatsapp_message', (msg) => {
                    this.handleIncomingMessage(msg);
                });

                this.socket.on('whatsapp_message', (msg) => {
                    this.handleIncomingMessage(msg);
                });

                this.socket.on('whatsapp_message_status', (data) => {
                    this.updateMessageStatus(data);
                });

                window.waSocket = this.socket;
            } catch (err) {
                console.warn('[BashFlowChat] Socket initialization notice:', err);
            }
        },

        handleIncomingMessage(msg) {
            if (!msg) return;
            if (typeof handleRealtimeWhatsAppMessage === 'function') {
                handleRealtimeWhatsAppMessage(msg);
            } else {
                this.messages.push(msg);
                if (this.activeChatId && (msg.chat_id === this.activeChatId || msg.sender_phone === this.activeChatId)) {
                    this.appendMessageBubble(msg);
                }
            }
        },

        updateMessageStatus(data) {
            if (!data || !data.message_id) return;
            const el = document.getElementById(`wa-status-${data.message_id}`);
            if (el) {
                el.className = `wa-msg-status ${data.status || 'sent'}`;
            }
        },

        selectChat(chatId, contactName, phone) {
            this.activeChatId = chatId || phone;
            window.activeWhatsAppChatId = this.activeChatId;

            // Update mobile viewport: show chat area, hide list on small screens
            const listPanel = document.querySelector('.whatsapp-conversations-sidebar, .wa-chat-list-panel');
            const chatPanel = document.querySelector('.whatsapp-chat-main-area, .wa-chat-detail-panel');
            if (window.innerWidth <= 768) {
                if (listPanel) listPanel.classList.add('mobile-hidden');
                if (chatPanel) {
                    chatPanel.classList.remove('mobile-hidden');
                    chatPanel.classList.add('mobile-fullscreen');
                }
            }

            if (typeof selectWhatsAppChat === 'function') {
                selectWhatsAppChat(chatId, contactName, phone);
            }
        },

        initMobileChatToggle() {
            const chatHeader = document.querySelector('.whatsapp-chat-header, .wa-chat-header');
            if (chatHeader && !document.getElementById('waMobileBackBtn')) {
                const backBtn = document.createElement('button');
                backBtn.id = 'waMobileBackBtn';
                backBtn.className = 'wa-mobile-back-btn';
                backBtn.innerHTML = '← Chats';
                backBtn.onclick = () => this.backToChatList();
                chatHeader.prepend(backBtn);
            }
        },

        backToChatList() {
            const listPanel = document.querySelector('.whatsapp-conversations-sidebar, .wa-chat-list-panel');
            const chatPanel = document.querySelector('.whatsapp-chat-main-area, .wa-chat-detail-panel');
            if (listPanel) listPanel.classList.remove('mobile-hidden');
            if (chatPanel) {
                chatPanel.classList.add('mobile-hidden');
                chatPanel.classList.remove('mobile-fullscreen');
            }
        },

        initChatBarListeners() {
            const sendBtn = document.getElementById('waReplySendBtn');
            if (sendBtn) {
                sendBtn.onclick = (e) => {
                    if (e && e.preventDefault) e.preventDefault();
                    if (typeof sendWhatsAppReply === 'function') {
                        sendWhatsAppReply();
                    }
                };
            }

            const input = document.getElementById('waReplyInput');
            if (input) {
                input.onkeydown = (e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        if (typeof sendWhatsAppReply === 'function') {
                            sendWhatsAppReply();
                        }
                    }
                };
            }
        },

        appendMessageBubble(msg) {
            const container = document.getElementById('whatsappMessagesList');
            if (!container) return;
            const bubble = document.createElement('div');
            const isOut = msg.is_outgoing || msg.direction === 'outbound';
            bubble.className = `wa-msg-row ${isOut ? 'wa-msg-out' : 'wa-msg-in'}`;
            bubble.innerHTML = `
                <div class="wa-msg-bubble">
                    <div class="wa-msg-text">${escapeHtml(msg.text || msg.body || '')}</div>
                    <div class="wa-msg-meta">
                        <span class="wa-msg-time">${msg.time || 'Now'}</span>
                    </div>
                </div>
            `;
            container.appendChild(bubble);
            container.scrollTop = container.scrollHeight;
        }
    };

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Expose module globally and bind legacy handlers
    window.BashFlowChat = BashFlowChat;
    window.initWhatsAppSocket = () => BashFlowChat.initSocket();
    window.initWhatsAppChatBarListeners = () => BashFlowChat.initChatBarListeners();

})(window, document);
