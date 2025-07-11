import art
from run_agent import run_agent_and_score
from load_scenarios import load_scenarios
from art.local import LocalBackend
from art.utils import iterate_dataset
from benchmark import benchmark

ROLLOUTS_PER_GROUP = 4
NUM_EPOCHS = 3
GROUPS_PER_STEP = 12
VALIDATION_FREQUENCY = 10
VALIDATION_NUM_SCENARIOS = 100
TRAINING_NUM_SCENARIOS = 1000


async def train():
    # For lecture-RL, the database already exists (lectures.db)
    # No need to generate it like in email-agent
    
    training_data = load_scenarios(split="train", limit=TRAINING_NUM_SCENARIOS)

    model = art.TrainableModel(
        base_model="Qwen/Qwen2.5-14B-Instruct",
        project="lecture-rl",
        name="lecture_model_1",
    )

    with LocalBackend() as backend:
        await model.register(backend)

        training_iterator = iterate_dataset(
            training_data,
            groups_per_step=GROUPS_PER_STEP,
            num_epochs=NUM_EPOCHS,
            initial_step=await model.get_step(),
        )

        for batch, epoch, global_step, epoch_step in training_iterator:
            if global_step % VALIDATION_FREQUENCY == 0:
                results, score = await benchmark(model, VALIDATION_NUM_SCENARIOS)
                await model.log(results)
            groups = []
            for scenario in batch:
                groups.append(
                    art.TrajectoryGroup(
                        (
                            run_agent_and_score(model, scenario)
                            for _ in range(ROLLOUTS_PER_GROUP)
                        )
                    )
                )

            finished_groups = await art.gather_trajectory_groups(groups)
            await model.train(finished_groups)


if __name__ == "__main__":
    import asyncio

    asyncio.run(train())