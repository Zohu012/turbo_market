import { useLocation } from "react-router-dom";
import { AZ } from "../../i18n/az";

export default function ComingSoon() {
  const { pathname } = useLocation();
  const slug = pathname.split("/").pop() ?? "";

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="text-5xl mb-4">🔜</div>
      <h2 className="text-xl font-semibold text-gray-700 mb-2">
        {AZ.dashboards.comingSoon}
      </h2>
      <p className="text-gray-400 text-sm">
        <code className="bg-gray-100 px-1 rounded">{slug}</code> paneli hazırlanır.
      </p>
    </div>
  );
}
