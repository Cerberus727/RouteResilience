import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Lab } from "../pages/Lab";

const SAMPLES = {
  total: 1, offset: 0, limit: 60,
  items: [{ image_id: "100034", folder: "train", phase1_subset: "val", has_ground_truth: true, has_phase1_mask: true }],
  dataset: { root: "x", paired_train: 6226, phase1_train: 4980, phase1_val: 1246, valid_images: 1243, test_images: 1101,
    split_check: { phase1_saved_masks: 44, matches_val_ids_first40_plus_demo: true } },
};

function mock(models: unknown) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.includes("/api/lab/models") ? models : url.includes("/api/lab/samples") ? SAMPLES : {};
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

describe("Segmentation lab", () => {
  it("explains an incompatible checkpoint and disables inference", async () => {
    mock([{ model_id: "unext", checkpoint: "best_road_model_unext.pth", loadable: false, family: "unext", diagnostic: "The UNeXt architecture lives in an external repository." }]);
    render(<MemoryRouter><Lab /></MemoryRouter>);
    expect(await screen.findByText(/external repository/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run inference/ })).toBeDisabled();
  });

  it("enables inference for a loadable model and confirms the reproduced split", async () => {
    mock([{ model_id: "deeplabv3", checkpoint: "best_road_model_deeplabv3.pth", loadable: true, family: "smp_deeplabv3plus", diagnostic: "ok" }]);
    render(<MemoryRouter><Lab /></MemoryRouter>);
    expect(await screen.findByText(/matches the 44 masks Phase I wrote/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Run inference/ })).toBeEnabled();
    expect(screen.getAllByText("held-out").length).toBeGreaterThan(0);
  });
});
