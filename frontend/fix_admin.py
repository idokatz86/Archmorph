import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    text = f.read()

# Replace mockResolvedValueOnce with mockResolvedValue for error tests
text = text.replace(
    """fetch.mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) })""",
    """fetch.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) })"""
)
text = text.replace(
    """fetch.mockRejectedValueOnce(new TypeError('Connection error'))""",
    """fetch.mockRejectedValue(new TypeError('Connection error'))"""
)
text = text.replace(
    """fetch.mockResolvedValueOnce({ ok: false, status: 503, json: () => Promise.resolve({}) })""",
    """fetch.mockResolvedValue({ ok: false, status: 503, json: () => Promise.resolve({}) })"""
)
text = text.replace(
    """expect(await screen.findByText("Network error — check your connection.")).toBeInTheDocument()""",
    """expect(await screen.findByText("Network error — check your connectio
with op {     text = f.read()

# Replace mockResolvedValueOnce with mockResolvedValue for error tests
text = text.replace( n
# Replace mockReservtext = text.replace(
    """fetch.mockResolvedValueOnce({ ok: false, Ad    """fetch.mockRere    """fetch.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) })"""
)
trc)
text = text.replace(
    """fetch.mockRejectedValueOnce(new TypeError('Connection error'))"t)
