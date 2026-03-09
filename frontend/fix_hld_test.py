import re
with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/DiagramTranslator/__tests__/HLDPanel.test.jsx', 'r') as f:
    text = f.read()

text = re.sub(
    r"it\('shows tab navigation', \(\) => \{.+?\}\)",
    """it('shows tab navigation', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Executive Summary')).toBeInTheDocument()
  })""",
    text,
    flags=re.DOTALL
)

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/DiagramTranslator/__tests__/HLDPanel.test.jsx', 'w') as f:
    f.write(text)
