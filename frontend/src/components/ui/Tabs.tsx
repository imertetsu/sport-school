import { useId, useState, type ReactNode } from 'react';
import './Tabs.css';

export interface TabItem {
  id: string;
  label: ReactNode;
  content: ReactNode;
}

export interface TabsProps {
  items: TabItem[];
  defaultTabId?: string;
}

export function Tabs({ items, defaultTabId }: TabsProps) {
  const baseId = useId();
  const [active, setActive] = useState<string>(defaultTabId ?? items[0]?.id);

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist">
        {items.map((item) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`${baseId}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              className={`tabs__tab${selected ? ' tabs__tab--active' : ''}`}
              onClick={() => setActive(item.id)}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${baseId}-panel-${item.id}`}
          aria-labelledby={`${baseId}-tab-${item.id}`}
          hidden={item.id !== active}
          className="tabs__panel"
        >
          {item.id === active ? item.content : null}
        </div>
      ))}
    </div>
  );
}
