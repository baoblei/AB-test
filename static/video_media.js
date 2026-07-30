(function (root, factory) {
    const exported = factory();
    if (typeof module === "object" && module.exports) module.exports = exported;
    if (root) root.VideoPlaybackGroup = exported.VideoPlaybackGroup;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    class VideoPlaybackGroup {
        constructor(options = {}) {
            this.sync = options.sync !== false;
            this.driftThreshold = Number(options.driftThreshold || 0.15);
            this.entries = new Map();
            this.propagating = false;
            this._looping = new Map();
            this._syncLoopKey = {};
        }

        add(id, media) {
            this.remove(id, false);
            const handlers = {
                play: () => this._mirrorPlay(id),
                pause: () => this._mirrorPause(id),
                seeking: () => this._mirrorTime(id),
                timeupdate: () => this._correctDrift(id),
                ended: () => this._loopFrom(id),
            };
            Object.entries(handlers).forEach(([type, handler]) => {
                media.addEventListener(type, handler);
            });
            this.entries.set(id, { media, handlers });
            return media;
        }

        remove(id, clearSource = false) {
            const entry = this.entries.get(id);
            if (!entry) return;
            Object.entries(entry.handlers).forEach(([type, handler]) => {
                entry.media.removeEventListener(type, handler);
            });
            entry.media.pause();
            if (clearSource) this._clearSource(entry.media);
            this.entries.delete(id);
            this._looping.delete(id);
            if (!this.entries.size) this._looping.delete(this._syncLoopKey);
        }

        setSync(enabled) {
            this.sync = Boolean(enabled);
            if (!this.sync || this.entries.size < 2) return;
            const first = this.entries.values().next().value;
            if (!first) return;
            this._runPropagated(() => {
                this.entries.forEach(entry => {
                    entry.media.currentTime = first.media.currentTime || 0;
                });
            });
        }

        async play(id) {
            const targets = this._targets(id);
            if (!targets.length) return;
            this.propagating = true;
            try {
                await Promise.all(targets.map(entry => {
                    const result = entry.media.play();
                    return result && typeof result.catch === "function"
                        ? result.catch(() => undefined)
                        : result;
                }));
            } finally {
                this.propagating = false;
            }
        }

        pause(id) {
            this._runPropagated(() => {
                this._targets(id).forEach(entry => entry.media.pause());
            });
        }

        seek(id, seconds) {
            const source = this.entries.get(id);
            if (!source) return;
            const duration = Number(source.media.duration);
            const requested = Number(seconds) || 0;
            const nextTime = Number.isFinite(duration) && duration > 0
                ? Math.max(0, Math.min(duration, requested))
                : Math.max(0, requested);
            this._runPropagated(() => {
                this._targets(id).forEach(entry => {
                    entry.media.currentTime = nextTime;
                });
            });
        }

        canUseFrameTools() {
            return [...this.entries.values()].every(entry => entry.media.paused);
        }

        captureFrame(id, mimeType = "image/png", quality) {
            const entry = this.entries.get(id);
            const media = entry && entry.media;
            if (!media || !media.paused || !media.videoWidth || !media.videoHeight) return null;
            if (typeof document === "undefined") return null;
            const canvas = document.createElement("canvas");
            canvas.width = media.videoWidth;
            canvas.height = media.videoHeight;
            const context = canvas.getContext("2d");
            if (!context) return null;
            context.drawImage(media, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL(mimeType, quality);
        }

        destroy() {
            this._runPropagated(() => {
                this.entries.forEach(entry => {
                    Object.entries(entry.handlers).forEach(([type, handler]) => {
                        entry.media.removeEventListener(type, handler);
                    });
                    entry.media.pause();
                    this._clearSource(entry.media);
                });
            });
            this.entries.clear();
            this._looping.clear();
        }

        _targets(id) {
            const source = this.entries.get(id);
            if (!source) return [];
            return this.sync ? [...this.entries.values()] : [source];
        }

        _runPropagated(callback) {
            const previous = this.propagating;
            this.propagating = true;
            try {
                callback();
            } finally {
                this.propagating = previous;
            }
        }

        _mirrorPlay(id) {
            if (this.propagating || !this.sync) return;
            this.play(id);
        }

        _mirrorPause(id) {
            if (this.propagating || !this.sync) return;
            this.pause(id);
        }

        _mirrorTime(id) {
            if (this.propagating || !this.sync) return;
            const source = this.entries.get(id);
            if (source) this.seek(id, source.media.currentTime);
        }

        _correctDrift(id) {
            if (this.propagating || !this.sync) return;
            const source = this.entries.get(id);
            if (!source) return;
            const time = Number(source.media.currentTime) || 0;
            this._runPropagated(() => {
                this.entries.forEach((entry, entryId) => {
                    if (entryId !== id && Math.abs((Number(entry.media.currentTime) || 0) - time) > this.driftThreshold) {
                        entry.media.currentTime = time;
                    }
                });
            });
        }

        _loopFrom(id) {
            const entry = this.entries.get(id);
            if (!entry) return;
            const syncLoop = this.sync;
            const key = syncLoop ? this._syncLoopKey : id;
            if (this._looping.has(key)) return;
            if (this.propagating && !this._looping.size) return;

            const token = {};
            this._looping.set(key, token);
            this.seek(id, 0);
            const replay = syncLoop ? this.play(id) : this._playEntry(entry);
            void Promise.resolve(replay).then(
                () => this._finishLoop(key, token),
                () => this._finishLoop(key, token),
            );
        }

        _playEntry(entry) {
            const result = entry.media.play();
            return result && typeof result.catch === "function"
                ? result.catch(() => undefined)
                : result;
        }

        _finishLoop(key, token) {
            if (this._looping.get(key) === token) this._looping.delete(key);
        }

        _clearSource(media) {
            media.removeAttribute("src");
            if (typeof media.querySelectorAll === "function") {
                media.querySelectorAll("source").forEach(source => source.remove());
            }
            media.load();
        }
    }

    return { VideoPlaybackGroup };
});
