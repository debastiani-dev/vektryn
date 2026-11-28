import { Check, ChevronDown, Globe, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
    filterLanguageOptions,
    formatLanguageBadge,
    getLanguageName,
    getLanguageOptions,
    type LanguageOption,
    UNKNOWN_LANGUAGE,
} from "../../utils/languages";
import { computePopoverCoords, type PopoverCoords } from "../../utils/popoverPosition";

export interface SpecialLanguageOption {
    code: string;
    label: string;
    hint?: string;
}

interface LanguageComboboxProps {
    id?: string;
    label?: string;
    value: string;
    onChange: (code: string) => void;
    specialOptions: ReadonlyArray<SpecialLanguageOption>;
    pinnedCodes?: ReadonlyArray<string>;
    placeholder?: string;
    disabled?: boolean;
    compact?: boolean;
}

interface FlattenedOption {
    code: string;
    label: string;
    badge?: string;
    group: "special" | "pinned" | "all";
    hint?: string;
}

export function LanguageCombobox({
    id,
    label,
    value,
    onChange,
    specialOptions,
    pinnedCodes = [],
    placeholder = "Search language or ISO code...",
    disabled = false,
    compact = false,
}: Readonly<LanguageComboboxProps>) {
    const generatedId = useId();
    const controlId = id ?? generatedId;
    const listboxId = `${controlId}-listbox`;

    const triggerRef = useRef<HTMLButtonElement>(null);
    const panelRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState("");
    const [activeIndex, setActiveIndex] = useState(0);
    const [coords, setCoords] = useState<PopoverCoords | null>(null);

    const allLanguages = useMemo(() => getLanguageOptions(pinnedCodes), [pinnedCodes]);

    const visibleOptions = useMemo<FlattenedOption[]>(() => {
        const q = search.trim().toLowerCase();
        const matchingSpecials: FlattenedOption[] = specialOptions
            .filter(
                (opt) =>
                    !q ||
                    opt.label.toLowerCase().includes(q) ||
                    opt.code.toLowerCase().includes(q),
            )
            .map((opt) => ({
                code: opt.code,
                label: opt.label,
                badge: opt.code && opt.code !== UNKNOWN_LANGUAGE ? opt.code.toUpperCase() : undefined,
                group: "special" as const,
                hint: opt.hint,
            }));

        const matchingLangs: LanguageOption[] = filterLanguageOptions(allLanguages, search);
        const langItems: FlattenedOption[] = matchingLangs.map((lang) => ({
            code: lang.code,
            label: lang.name,
            badge: lang.code.toUpperCase(),
            group: lang.pinned ? "pinned" : "all",
        }));

        return [...matchingSpecials, ...langItems];
    }, [allLanguages, search, specialOptions]);

    const selectedDisplay = useMemo(() => {
        const special = specialOptions.find((opt) => opt.code === value);
        if (special) {
            return special.label;
        }
        if (!value || value === UNKNOWN_LANGUAGE) {
            return specialOptions[0]?.label ?? "Unknown";
        }
        return `${getLanguageName(value)} (${formatLanguageBadge(value)})`;
    }, [specialOptions, value]);

    useEffect(() => {
        if (!open) return;

        const updatePosition = () => {
            const trigger = triggerRef.current;
            if (!trigger) return;
            const rect = trigger.getBoundingClientRect();
            const width = Math.max(rect.width, 260);
            setCoords(
                computePopoverCoords(rect, window.innerWidth, window.innerHeight, {
                    desktopWidth: width,
                    mobileWidth: width,
                    minWidth: 240,
                    offsetY: 6,
                }),
            );
        };

        updatePosition();
        requestAnimationFrame(() => searchInputRef.current?.focus());

        const handleOutside = (event: MouseEvent) => {
            const target = event.target as Node | null;
            if (
                target &&
                !triggerRef.current?.contains(target) &&
                !panelRef.current?.contains(target)
            ) {
                setOpen(false);
            }
        };

        window.addEventListener("resize", updatePosition);
        window.addEventListener("scroll", updatePosition, true);
        document.addEventListener("mousedown", handleOutside);
        return () => {
            window.removeEventListener("resize", updatePosition);
            window.removeEventListener("scroll", updatePosition, true);
            document.removeEventListener("mousedown", handleOutside);
        };
    }, [open]);

    const handleSelect = (code: string) => {
        onChange(code);
        setOpen(false);
        setSearch("");
        setActiveIndex(0);
    };

    const handleSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "Escape") {
            event.preventDefault();
            setOpen(false);
            triggerRef.current?.focus();
            return;
        }
        if (event.key === "ArrowDown") {
            event.preventDefault();
            setActiveIndex((prev) =>
                visibleOptions.length === 0 ? 0 : (prev + 1) % visibleOptions.length,
            );
            return;
        }
        if (event.key === "ArrowUp") {
            event.preventDefault();
            setActiveIndex((prev) =>
                visibleOptions.length === 0
                    ? 0
                    : (prev - 1 + visibleOptions.length) % visibleOptions.length,
            );
            return;
        }
        if (event.key === "Enter" && visibleOptions[activeIndex]) {
            event.preventDefault();
            handleSelect(visibleOptions[activeIndex].code);
        }
    };

    const triggerClasses = compact
        ? "flex w-full items-center justify-between gap-2 rounded-lg border border-zinc-800 bg-zinc-950/90 px-2.5 py-2 text-left text-xs text-zinc-200 transition hover:border-zinc-700 focus:border-violet-500/60 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        : "flex w-full items-center justify-between gap-2 rounded-xl border border-zinc-800 bg-zinc-950/80 px-3.5 py-2.5 text-left text-sm text-zinc-100 transition hover:border-zinc-700 focus:border-violet-500/60 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50";

    const popover =
        open && coords && typeof document !== "undefined"
            ? createPortal(
                  <div
                      ref={panelRef}
                      style={{
                          position: "fixed",
                          top: coords.top,
                          left: coords.left,
                          width: Math.max(coords.width, 260),
                      }}
                      className="z-50 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl shadow-black/70 ring-1 ring-white/5"
                  >
                      <div className="border-b border-zinc-800/80 p-2">
                          <div className="relative flex items-center">
                              <Search
                                  className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-zinc-500"
                                  aria-hidden="true"
                              />
                              <input
                                  ref={searchInputRef}
                                  type="text"
                                  value={search}
                                  onChange={(e) => {
                                      setSearch(e.target.value);
                                      setActiveIndex(0);
                                  }}
                                  onKeyDown={handleSearchKeyDown}
                                  placeholder={placeholder}
                                  aria-label={placeholder}
                                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900/90 py-1.5 pr-2.5 pl-8 text-xs text-zinc-100 placeholder:text-zinc-500 focus:border-violet-500/60 focus:outline-none"
                              />
                          </div>
                      </div>

                      <div
                          id={listboxId}
                          role="listbox"
                          aria-label={label ?? "Language options"}
                          className="max-h-60 overflow-y-auto p-1"
                      >
                          {visibleOptions.length === 0 ? (
                              <div className="px-3 py-4 text-center text-xs text-zinc-500">
                                  No matching ISO 639-1 language
                              </div>
                          ) : (
                              visibleOptions.map((option, idx) => {
                                  const prevGroup = idx > 0 ? visibleOptions[idx - 1]?.group : null;
                                  const showPinnedHeader =
                                      option.group === "pinned" && prevGroup !== "pinned";
                                  const showAllHeader =
                                      option.group === "all" &&
                                      prevGroup !== "all" &&
                                      prevGroup !== null;
                                  const isSelected = option.code === value;
                                  const isHighlighted = idx === activeIndex;

                                  return (
                                      <div key={`${option.group}:${option.code || "all"}`}>
                                          {showPinnedHeader && (
                                              <div className="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-violet-400">
                                                  Active Resume Languages
                                              </div>
                                          )}
                                          {showAllHeader && (
                                              <div className="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                                                  All ISO 639-1 Languages
                                              </div>
                                          )}
                                          <button
                                              type="button"
                                              role="option"
                                              aria-selected={isSelected}
                                              onMouseEnter={() => setActiveIndex(idx)}
                                              onClick={() => handleSelect(option.code)}
                                              className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition ${
                                                  isHighlighted
                                                      ? "bg-zinc-800/90 text-zinc-100"
                                                      : "text-zinc-300 hover:bg-zinc-900"
                                              }`}
                                          >
                                              <span className="flex min-w-0 items-center gap-2">
                                                  <span className="truncate font-medium">
                                                      {option.label}
                                                  </span>
                                                  {option.hint && (
                                                      <span className="truncate text-[10px] text-zinc-500">
                                                          {option.hint}
                                                      </span>
                                                  )}
                                              </span>
                                              <span className="flex shrink-0 items-center gap-1.5">
                                                  {option.badge && (
                                                      <span className="rounded bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400 ring-1 ring-zinc-800">
                                                          {option.badge}
                                                      </span>
                                                  )}
                                                  {isSelected && (
                                                      <Check className="h-3.5 w-3.5 text-violet-400" />
                                                  )}
                                              </span>
                                          </button>
                                      </div>
                                  );
                              })
                          )}
                      </div>
                  </div>,
                  document.body,
              )
            : null;

    return (
        <div className="min-w-0">
            {label && (
                <label
                    htmlFor={controlId}
                    className={
                        compact
                            ? "mb-1 block text-[11px] font-medium uppercase tracking-wider text-zinc-500"
                            : "mb-1.5 block text-xs font-medium text-zinc-300"
                    }
                >
                    {label}
                </label>
            )}
            <button
                ref={triggerRef}
                id={controlId}
                type="button"
                role="combobox"
                aria-expanded={open}
                aria-controls={listboxId}
                aria-haspopup="listbox"
                disabled={disabled}
                onClick={() => {
                    setOpen((prev) => !prev);
                    setActiveIndex(0);
                }}
                className={triggerClasses}
            >
                <span className="flex min-w-0 items-center gap-1.5">
                    <Globe className="h-3.5 w-3.5 shrink-0 text-zinc-500" aria-hidden="true" />
                    <span className="truncate">{selectedDisplay}</span>
                </span>
                <ChevronDown
                    className={`h-3.5 w-3.5 shrink-0 text-zinc-500 transition-transform ${
                        open ? "rotate-180" : ""
                    }`}
                    aria-hidden="true"
                />
            </button>
            {popover}
        </div>
    );
}
