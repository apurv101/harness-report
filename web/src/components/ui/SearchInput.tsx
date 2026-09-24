import { Icon } from './Icon'

/** The search box above a list, with or without the magnifier the flow cards use. */
export function SearchInput({ value, onChange, placeholder, label, icon }: {
  value: string
  onChange: (value: string) => void
  placeholder: string
  label: string
  icon?: boolean
}) {
  return (
    <div className="search-wrap">
      {icon && <Icon name="search" />}
      <input type="search" value={value} aria-label={label} placeholder={placeholder}
             autoComplete="off" onChange={e => onChange(e.target.value)} />
    </div>
  )
}
