// 【模块】状态管理类：负责所有动态状态
class BotState {
    constructor() {
        this.isExecuting = false;
        this.consecutiveFailures = 0;
        this.gasSpentTodayUSD = 0;
        this.dailyResetTimestamp = this.getNextUTCDay();
        this.isPaused = false;
        this.pauseTimeout = null;

        this.tokenPairs = {};
        this.baseGasEstimate = 800000n; // Default value
    }
    
    getNextUTCDay() {
        const now = new Date();
        const nextDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
        return nextDay.getTime();
    }
}

module.exports = { BotState }; 