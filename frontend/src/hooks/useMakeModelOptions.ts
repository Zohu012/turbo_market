import { useEffect, useState } from "react";
import { vehiclesApi } from "../api/client";

export function useMakeModelOptions(selectedMake: string) {
  const [makes, setMakes] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);

  useEffect(() => {
    vehiclesApi.makes().then((r) => setMakes(r.data.makes)).catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedMake) {
      vehiclesApi.models(selectedMake).then((r) => setModels(r.data.models)).catch(() => {});
    } else {
      setModels([]);
    }
  }, [selectedMake]);

  return { makes, models };
}
