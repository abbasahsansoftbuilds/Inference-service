import { useState, useEffect } from 'react'

function App() {
    const [servers, setServers] = useState([])

    const fetchStatus = () => {
        fetch('/api/status', {
            headers: {
                'Authorization': 'Bearer dev-token'
            }
        })
            .then(res => res.json())
            .then(data => setServers(data))
            .catch(err => console.error(err))
    }

    useEffect(() => {
        fetchStatus()
        // Refresh every 5 seconds
        const interval = setInterval(fetchStatus, 5000)
        return () => clearInterval(interval)
    }, [])

    const launch = (uuid) => {
        // Access via Traefik ingress on port 8080
        window.open(`http://localhost:8080/${uuid}/`, '_blank')
    }

    const formatDate = (dateStr) => {
        if (!dateStr) return '-'
        const date = new Date(dateStr)
        return date.toLocaleString()
    }

    return (
        <div className="container">
            <h1>Inference Servers</h1>
            <p style={{color: '#666', fontSize: '14px'}}>Auto-refreshes every 5 seconds</p>
            <table>
                <thead>
                    <tr>
                        <th>Model</th>
                        <th>UUID</th>
                        <th>Status</th>
                        <th>Memory (MB)</th>
                        <th>Endpoint</th>
                        <th>Last Updated</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {servers.length === 0 ? (
                        <tr><td colSpan="7" style={{textAlign: 'center'}}>No servers running</td></tr>
                    ) : (
                        servers.map(server => (
                            <tr key={server.uuid}>
                                <td>{server.model_name}</td>
                                <td><code>{server.uuid}</code></td>
                                <td style={{color: server.status === 'Running' ? 'green' : 'orange'}}>{server.status}</td>
                                <td>{server.memory_usage_mb}</td>
                                <td><a href={`http://localhost:8080/${server.uuid}/`} target="_blank" rel="noreferrer">/{server.uuid}</a></td>
                                <td>{formatDate(server.updated_at)}</td>
                                <td>
                                    <button onClick={() => launch(server.uuid)}>Launch</button>
                                </td>
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    )
}

export default App
