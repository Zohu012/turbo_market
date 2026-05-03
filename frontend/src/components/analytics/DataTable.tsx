import {
  ColumnDef,
  SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";

interface Props<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  total?: number;
  pageIndex?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  sorting?: SortingState;
  onSortingChange?: (s: SortingState) => void;
  loading?: boolean;
  emptyText?: string;
  rowHref?: (row: T) => string;
  manualPagination?: boolean;
  manualSorting?: boolean;
}

export default function DataTable<T>({
  columns,
  data,
  total,
  pageIndex = 0,
  pageSize = 50,
  onPageChange,
  sorting: externalSorting,
  onSortingChange,
  loading,
  emptyText = "Məlumat yoxdur",
  rowHref,
  manualPagination = false,
  manualSorting = false,
}: Props<T>) {
  const [internalSorting, setInternalSorting] = useState<SortingState>([]);
  const sorting = externalSorting ?? internalSorting;
  const setSorting = onSortingChange ?? setInternalSorting;

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: (updater) => setSorting(typeof updater === "function" ? updater(sorting) : updater),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: manualSorting ? undefined : getSortedRowModel(),
    manualPagination,
    manualSorting,
  });

  const totalPages = total !== undefined ? Math.ceil(total / pageSize) : undefined;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-max">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="text-xs text-gray-500 uppercase border-b">
              {hg.headers.map((h) => (
                <th
                  key={h.id}
                  className={`py-2 px-2 text-left whitespace-nowrap ${h.column.getCanSort() ? "cursor-pointer select-none hover:text-gray-800" : ""}`}
                  onClick={h.column.getToggleSortingHandler()}
                >
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {h.column.getIsSorted() === "asc" ? " ↑" : h.column.getIsSorted() === "desc" ? " ↓" : ""}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y">
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-gray-400">
                Yüklənir…
              </td>
            </tr>
          ) : table.getRowModel().rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="py-8 text-center text-gray-400">
                {emptyText}
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => {
              const href = rowHref?.(row.original);
              return (
                <tr
                  key={row.id}
                  className={`hover:bg-gray-50 ${href ? "cursor-pointer" : ""}`}
                  onClick={href ? () => window.open(href, "_blank") : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="py-2 px-2 whitespace-nowrap">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>

      {manualPagination && totalPages !== undefined && totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-sm text-gray-500 px-2">
          <span>
            {(pageIndex * pageSize) + 1}–{Math.min((pageIndex + 1) * pageSize, total ?? 0)} / {total}
          </span>
          <div className="flex gap-1">
            <button
              disabled={pageIndex === 0}
              onClick={() => onPageChange?.(pageIndex - 1)}
              className="px-2 py-1 rounded border disabled:opacity-30 hover:bg-gray-100"
            >
              ‹
            </button>
            <button
              disabled={pageIndex >= totalPages - 1}
              onClick={() => onPageChange?.(pageIndex + 1)}
              className="px-2 py-1 rounded border disabled:opacity-30 hover:bg-gray-100"
            >
              ›
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
