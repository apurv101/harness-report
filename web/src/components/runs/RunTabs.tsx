import type { ReactNode } from 'react'

export interface Tab {
  id: string
  label: string
  count?: number
  panel: () => ReactNode
}

/** The run's tab bar.  The selected tab lives in the URL, so a refresh or a link keeps it. */
export function RunTabs({ tabs, selected, onSelect }: {
  tabs: Tab[]
  selected: string
  onSelect: (id: string) => void
}) {
  const current = tabs.find(t => t.id === selected) ?? tabs[0]
  return (
    <>
      <nav className="tabs">
        {tabs.map(tab => (
          <button key={tab.id} className={tab.id === current.id ? 'on' : undefined} onClick={() => onSelect(tab.id)}>
            {tab.label}{tab.count != null && <span className="n">{tab.count}</span>}
          </button>
        ))}
      </nav>
      <section className="panel on">{current.panel()}</section>
    </>
  )
}
