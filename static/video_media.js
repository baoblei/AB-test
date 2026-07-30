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
            this._propagationDepth = 0;
            this._looping = new Set();
        }

        add(id, media) {
            this.remove(id, false);
            const handlers = {
                play: () => this._mirrorPlay(id),
                pause: () => this._mirrorPause(id),
                timeupdate: () => this._correctDrift(id),
                ended: () => this._loopFrom(id),
            };
            Object.entries(handlers).forEach(([type, handler]) => {
                media.addEventListener(type, handler);
            });
            this.entries.set(id, { id, media, handlers });
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
            [...this._looping].forEach(token => this._finishLoopTarget(token, entry));
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
            await this._playEntries(targets);
        }

        async _playEntries(targets, onSettled) {
            this._beginPropagation();
            try {
                await Promise.all(targets.map(entry => {
                    const result = entry.media.play();
                    const pending = result && typeof result.catch === "function"
                        ? result.catch(() => undefined)
                        : result;
                    return Promise.resolve(pending).then(value => {
                        if (onSettled) onSettled(entry);
                        return value;
                    });
                }));
            } finally {
                this._endPropagation();
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
            this._beginPropagation();
            try {
                callback();
            } finally {
                this._endPropagation();
            }
        }

        _beginPropagation() {
            this._propagationDepth += 1;
            this.propagating = true;
        }

        _endPropagation() {
            this._propagationDepth = Math.max(0, this._propagationDepth - 1);
            this.propagating = this._propagationDepth > 0;
        }

        _mirrorPlay(id) {
            if (this.propagating || !this.sync) return;
            this.play(id);
        }

        _mirrorPause(id) {
            if (this.propagating || !this.sync) return;
            this.pause(id);
        }

        _correctDrift(id) {
            if (this.propagating || !this.sync) return;
            const source = this.entries.get(id);
            const leader = this.entries.values().next().value;
            if (!source || source !== leader || source.media.seeking) return;
            const sourceReadyState = Number(source.media.readyState);
            if (Number.isFinite(sourceReadyState) && sourceReadyState < 3) return;
            const time = Number(source.media.currentTime) || 0;
            this._runPropagated(() => {
                this.entries.forEach((entry, entryId) => {
                    if (entryId === id || entry.media.seeking) return;
                    const readyState = Number(entry.media.readyState);
                    if (Number.isFinite(readyState) && readyState < 3) return;
                    if (Math.abs((Number(entry.media.currentTime) || 0) - time) > this.driftThreshold) {
                        entry.media.currentTime = time;
                    }
                });
            });
        }

        _loopFrom(id) {
            const entry = this.entries.get(id);
            if (!entry) return;
            const requested = this.sync ? [...this.entries.values()] : [entry];
            this._runPropagated(() => {
                requested.forEach(target => {
                    if (this.entries.get(target.id) === target) target.media.currentTime = 0;
                });
            });
            const targets = requested.filter(target => (
                this.entries.get(target.id) === target && !this._loopCovers(target)
            ));
            if (!targets.length) return;

            const token = { targets: new Set(targets) };
            this._looping.add(token);
            const replay = this._playEntries(
                targets,
                target => this._finishLoopTarget(token, target),
            );
            void Promise.resolve(replay).then(
                () => this._finishLoop(token),
                () => this._finishLoop(token),
            );
        }

        _loopCovers(entry) {
            for (const token of this._looping) {
                if (token.targets.has(entry)) return true;
            }
            return false;
        }

        _finishLoop(token) {
            this._looping.delete(token);
        }

        _finishLoopTarget(token, target) {
            token.targets.delete(target);
            if (!token.targets.size) this._finishLoop(token);
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
