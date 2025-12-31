/**
 * NEXUS WALLET - Frontend JavaScript
 */

// Toast Notifications
class ToastManager {
    constructor() {
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        document.body.appendChild(this.container);
    }
    
    show(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        
        this.container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
    
    success(message) {
        this.show(message, 'success');
    }
    
    error(message) {
        this.show(message, 'error');
    }
}

const toast = new ToastManager();

// Copy to Clipboard
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        toast.success('Copied to clipboard!');
    } catch (err) {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.select();
        
        try {
            document.execCommand('copy');
            toast.success('Copied to clipboard!');
        } catch (e) {
            toast.error('Failed to copy');
        }
        
        document.body.removeChild(textArea);
    }
}

// Format Address
function formatAddress(address, startChars = 6, endChars = 4) {
    if (!address || address.length < startChars + endChars) return address;
    return `${address.slice(0, startChars)}...${address.slice(-endChars)}`;
}

// Format Balance
function formatBalance(balance, decimals = 4) {
    const num = parseFloat(balance);
    if (isNaN(num)) return '0';
    
    if (num === 0) return '0';
    if (num < 0.0001) return '< 0.0001';
    
    return num.toLocaleString('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals
    });
}

// API Client
class NexusAPI {
    constructor(baseUrl = '/api') {
        this.baseUrl = baseUrl;
    }
    
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        
        try {
            const response = await fetch(url, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Request failed');
            }
            
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }
    
    async getNetworks() {
        return this.request('/networks');
    }
    
    async getBalance(network, address) {
        return this.request(`/balance/${network}/${address}`);
    }
    
    async estimateGas(network, from, to, amount) {
        return this.request(`/gas/${network}?from_addr=${from}&to_addr=${to}&amount=${amount}`);
    }
    
    async getTransactionStatus(network, txHash) {
        return this.request(`/tx/${network}/${txHash}`);
    }
    
    async createWallet(network, mnemonic = null) {
        return this.request('/wallet/create', {
            method: 'POST',
            body: JSON.stringify({ network, mnemonic })
        });
    }
}

const api = new NexusAPI();

// Auto-refresh balances
class BalanceRefresher {
    constructor(interval = 30000) {
        this.interval = interval;
        this.timerId = null;
    }
    
    start() {
        this.refresh();
        this.timerId = setInterval(() => this.refresh(), this.interval);
    }
    
    stop() {
        if (this.timerId) {
            clearInterval(this.timerId);
            this.timerId = null;
        }
    }
    
    async refresh() {
        const balanceElements = document.querySelectorAll('[data-balance-address]');
        
        for (const el of balanceElements) {
            const network = el.dataset.balanceNetwork;
            const address = el.dataset.balanceAddress;
            
            if (network && address) {
                try {
                    const data = await api.getBalance(network, address);
                    el.textContent = formatBalance(data.balance);
                } catch (error) {
                    console.error('Balance refresh error:', error);
                }
            }
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Start balance refresher if on dashboard
    if (document.querySelector('.dashboard')) {
        const refresher = new BalanceRefresher(30000);
        refresher.start();
    }
    
    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner"></span> Processing...';
            }
        });
    });
    
    // Network selection highlight
    const networkOptions = document.querySelectorAll('.network-option input');
    networkOptions.forEach(input => {
        input.addEventListener('change', () => {
            document.querySelectorAll('.network-option-content').forEach(el => {
                el.classList.remove('selected');
            });
            if (input.checked) {
                input.nextElementSibling.classList.add('selected');
            }
        });
    });
});

// Export for global use
window.copyToClipboard = copyToClipboard;
window.formatAddress = formatAddress;
window.formatBalance = formatBalance;
window.api = api;
window.toast = toast;