import { useState, useEffect } from 'react'

function App() {
    const [servers, setServers] = useState([])
    const [models, setModels] = useState([])
    const [error, setError] = useState(null)
    const [loading, setLoading] = useState(true)
    const [token, setToken] = useState(localStorage.getItem('jwt_token') || '')
    const [showLogin, setShowLogin] = useState(!token)
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [newModelName, setNewModelName] = useState('')
    const [showServeModal, setShowServeModal] = useState(false)

    const apiBase = '/api'

    const fetchWithAuth = async (url, options = {}) => {
        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        }
        const response = await fetch(url, { ...options, headers })
        if (response.status === 401) {
            setShowLogin(true)
            setToken('')
            localStorage.removeItem('jwt_token')
            throw new Error('Authentication required')
        }
        return response
    }

    const login = async (e) => {
        e.preventDefault()
        try {
            const response = await fetch(`${apiBase}/auth/token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            })
            if (!response.ok) {
                throw new Error('Invalid credentials')
            }
            const data = await response.json()
            setToken(data.access_token)
            localStorage.setItem('jwt_token', data.access_token)
            setShowLogin(false)
            setError(null)
        } catch (err) {
            setError(err.message)
        }
    }

    const logout = () => {
        setToken('')
        localStorage.removeItem('jwt_token')
        setShowLogin(true)
        setServers([])
        setModels([])
    }

    const fetchStatus = async () => {
        if (!token) return
        try {
            const res = await fetchWithAuth(`${apiBase}/status`)
            if (!res.ok) {
                throw new Error(`Server error: ${res.status}`)
            }
            const data = await res.json()
            setServers(Array.isArray(data) ? data : [])
            setError(null)
        } catch (err) {
            console.error(err)
            if (!err.message.includes('Authentication')) {
                setError(err.message)
            }
            setServers([])
        } finally {
            setLoading(false)
        }
    }

    const fetchModels = async () => {
        if (!token) return
        try {
            const res = await fetchWithAuth(`${apiBase}/models`)
            if (!res.ok) return
            const data = await res.json()
            setModels(Array.isArray(data) ? data : [])
        } catch (err) {
            console.error('Failed to fetch models:', err)
        }
    }

    useEffect(() => {
        if (token) {
            fetchStatus()
            fetchModels()
            const interval = setInterval(() => {
                fetchStatus()
                fetchModels()
            }, 5000)
            return () => clearInterval(interval)
        }
    }, [token])

    const serveModel = async (modelUuid, modelName) => {
        try {
            const res = await fetchWithAuth(`${apiBase}/serve`, {
                method: 'POST',
                body: JSON.stringify({
                    model_uuid: modelUuid,
                    model_name: modelName,
                    replicas: 1
                })
            })
            if (!res.ok) {
                const data = await res.json()
                throw new Error(data.detail || 'Failed to serve model')
            }
            fetchStatus()
        } catch (err) {
            setError(err.message)
        }
    }

    const stopServer = async (uuid) => {
        try {
            const res = await fetchWithAuth(`${apiBase}/stop/${uuid}`, {
                method: 'DELETE'
            })
            if (!res.ok) {
                const data = await res.json()
                throw new Error(data.detail || 'Failed to stop server')
            }
            fetchStatus()
        } catch (err) {
            setError(err.message)
        }
    }

    const launch = (uuid) => {
        window.open(`http://localhost:8080/${uuid}/`, '_blank')
    }

    const formatDate = (dateStr) => {
        if (!dateStr) return '-'
        const date = new Date(dateStr)
        return date.toLocaleString()
    }

    const formatBytes = (bytes) => {
        if (!bytes || bytes === 0) return '-'
        const mb = bytes / (1024 * 1024)
        if (mb >= 1024) {
            return `${(mb / 1024).toFixed(2)} GB`
        }
        return `${mb.toFixed(0)} MB`
    }

    const getStatusColor = (status) => {
        switch (status?.toLowerCase()) {
            case 'running': return '#4caf50'
            case 'pending': return '#ff9800'
            case 'downloading': return '#2196f3'
            case 'failed': return '#f44336'
            default: return '#9e9e9e'
        }
    }

    if (showLogin) {
        return (
            <div className="container" style={{ maxWidth: '400px', marginTop: '100px' }}>
                <h1>Inference Service Login</h1>
                {error && (
                    <div className="error-banner">
                        <strong>⚠️ Error:</strong> {error}
                    </div>
                )}
                <form onSubmit={login} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <input
                        type="text"
                        placeholder="Username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        required
                        style={{ padding: '12px', fontSize: '16px' }}
                    />
                    <input
                        type="password"
                        placeholder="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        style={{ padding: '12px', fontSize: '16px' }}
                    />
                    <button type="submit" style={{ padding: '12px', fontSize: '16px' }}>
                        Login
                    </button>
                </form>
            </div>
        )
    }

    return (
        <div className="container">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h1>Inference Servers</h1>
                <button onClick={logout} style={{ background: '#666' }}>Logout</button>
            </div>
            <p style={{ color: '#666', fontSize: '14px' }}>Auto-refreshes every 5 seconds</p>

            {error && (
                <div className="error-banner">
                    <strong>⚠️ Error:</strong> {error}
                    <button onClick={() => setError(null)} style={{ marginLeft: '16px', padding: '4px 8px' }}>
                        Dismiss
                    </button>
                </div>
            )}

            {/* Available Models Section */}
            <div style={{ marginBottom: '32px' }}>
                <h2>Available Models</h2>
                {models.length === 0 ? (
                    <p style={{ color: '#666' }}>No models available in MinIO. Download models from Quant service first.</p>
                ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
                        {models.map(model => (
                            <div key={model.uuid} className="model-card">
                                <h3>{model.model_name}</h3>
                                <div className="model-details">
                                    <span>UUID: <code>{model.uuid.substring(0, 8)}...</code></span>
                                    <span>Size: {formatBytes(model.file_size_bytes)}</span>
                                    <span>Quant: {model.quant_level || 'N/A'}</span>
                                </div>
                                <button 
                                    onClick={() => serveModel(model.uuid, model.model_name)}
                                    style={{ marginTop: '12px', width: '100%' }}
                                >
                                    Serve Model
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Running Servers Section */}
            <h2>Running Servers</h2>
            {loading ? (
                <p>Loading...</p>
            ) : (
                <table>
                    <thead>
                        <tr>
                            <th>Model</th>
                            <th>Server UUID</th>
                            <th>Status</th>
                            <th>Memory (Max)</th>
                            <th>CPU %</th>
                            <th>Created</th>
                            <th>Started</th>
                            <th>Gateway URL</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {servers.length === 0 ? (
                            <tr><td colSpan="9" style={{ textAlign: 'center' }}>No servers running</td></tr>
                        ) : (
                            servers.map(server => (
                                <tr key={server.uuid}>
                                    <td>{server.model_name}</td>
                                    <td><code title={server.uuid}>{server.uuid.substring(0, 8)}...</code></td>
                                    <td>
                                        <span style={{ 
                                            color: getStatusColor(server.status),
                                            fontWeight: 'bold'
                                        }}>
                                            {server.status}
                                        </span>
                                    </td>
                                    <td>{server.memory_max_mb ? `${server.memory_max_mb} MB` : '-'}</td>
                                    <td>{server.cpu_usage_percent ? `${server.cpu_usage_percent.toFixed(1)}%` : '-'}</td>
                                    <td>{formatDate(server.created_at)}</td>
                                    <td>{formatDate(server.started_at)}</td>
                                    <td>
                                        {server.gateway_url ? (
                                            <a href={server.gateway_url} target="_blank" rel="noreferrer">
                                                {server.gateway_url}
                                            </a>
                                        ) : (
                                            <span style={{ color: '#999' }}>Pending...</span>
                                        )}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button 
                                                onClick={() => launch(server.uuid)}
                                                disabled={server.status !== 'running'}
                                                style={{ 
                                                    opacity: server.status !== 'running' ? 0.5 : 1 
                                                }}
                                            >
                                                Launch
                                            </button>
                                            <button 
                                                onClick={() => stopServer(server.uuid)}
                                                style={{ background: '#f44336' }}
                                            >
                                                Stop
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            )}
        </div>
    )
}

export default App
