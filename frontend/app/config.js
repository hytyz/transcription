/**
 * runtime configuration for the frontend
 */

const config = {
    /** base url for gateway */
    BASE_URL: "https://sytyz.tailec0aa4.ts.net",
    
    /** websocket url for transcription status updates */
    WS_URL: "wss://pataka.tail2feabe.ts.net/ws/status",
};

Object.freeze(config);

export default config;
